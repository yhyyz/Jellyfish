from __future__ import annotations

"""文件相关工具：从 URL 或 base64 内容创建 FileItem，并上传到对象存储。"""

import asyncio
import base64
import os
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.studio import FileItem, FileType
from app.models.types import FileUsageKind


_FILE_INSERT_MAX_ATTEMPTS = 30
_FILE_INSERT_MAX_BACKOFF_S = 10.0


async def _add_and_flush_with_retry(session: AsyncSession, file_obj: FileItem) -> None:
    """落库 FileItem 并 flush；遇到 SQLite "database is locked" 时使用嵌套
    事务（SAVEPOINT）隔离失败并自动重试。

    背景：W19b-T1e 把 connect_args timeout=60.0 装进 sqlite3.connect()，
    本地 Check A 验证 PRAGMA busy_timeout=60000。但 celery worker 内
    aiosqlite 后台线程模型下，busy_timeout 实测不可靠（INSERT 立即返回
    SQLITE_BUSY，不等待）。修复策略：
    1) SAVEPOINT 包住单条 INSERT，失败后只回滚这一行；
    2) 每次重试前主动 PRAGMA busy_timeout=60000 强制刷写；
    3) 指数退避 + 抖动，最多 30 次（封顶 10s）≈ 累计 ~3 min 的重试预算。

    重试预算大于任何合理的"另一个 writer 持有事务"时间窗，足以兜底
    所有 in-process / cross-process / WAL checkpoint 类竞态。
    """
    last_exc: OperationalError | None = None
    for attempt in range(_FILE_INSERT_MAX_ATTEMPTS):
        if attempt > 0:
            backoff = min(0.3 * (1.5 ** (attempt - 1)), _FILE_INSERT_MAX_BACKOFF_S)
            await asyncio.sleep(backoff + random.uniform(0, 0.2))
        try:
            await session.execute(text("PRAGMA busy_timeout=60000"))
        except OperationalError:
            pass  # 极个别场景下连 PRAGMA 都被锁，让外层重试覆盖
        try:
            async with session.begin_nested():
                session.add(file_obj)
                await session.flush()
            return
        except OperationalError as exc:
            msg = str(getattr(exc, "orig", exc) or exc).lower()
            if "database is locked" not in msg and "database table is locked" not in msg:
                raise
            last_exc = exc
    if last_exc is not None:
        raise last_exc


async def _infer_file_type_from_ext(ext: str) -> FileType:
    ext = ext.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return FileType.image
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
        return FileType.video
    # 默认按图片处理，调用方若有更精细需求可在外层再封装
    return FileType.image


@dataclass(frozen=True)
class FileUsageCreateParams:
    """创建 FileItem 后写入 file_usages 的参数。"""

    project_id: str
    chapter_id: str | None = None
    shot_id: str | None = None
    usage_kind: FileUsageKind | str = FileUsageKind.api
    source_ref: str | None = None


async def _infer_file_type_from_content_type(content_type: str | None) -> FileType:
    if not content_type:
        return FileType.image
    ct = content_type.lower()
    if ct.startswith("image/"):
        return FileType.image
    if ct.startswith("video/"):
        return FileType.video
    if ct.startswith("audio/"):
        return FileType.audio
    return FileType.image


async def create_file_from_url_or_b64(
    session: AsyncSession,
    *,
    url: str | None = None,
    b64_data: str | None = None,
    name: str | None = None,
    prefix: str = "files",
    url_request_headers: dict[str, str] | None = None,
    httpx_timeout: float | None = None,
    usage: FileUsageCreateParams | None = None,
) -> FileItem:
    """从远端 URL 或 base64 内容创建 FileItem。

    - 若提供 url：会先下载内容，推断 content_type 和后缀；
    - 若提供 b64_data：优先解析 data URL 前缀中的 MIME 类型，否则默认 image/png；
    - 始终通过 storage.upload_file 上传到对象存储，再创建 FileItem 记录并返回。
    - url_request_headers / httpx_timeout：用于需鉴权或大文件下载（如 OpenAI /videos/{id}/content）。
    """
    if not url and not b64_data:
        raise ValueError("create_file_from_url_or_b64 需要提供 url 或 b64_data 至少其一")

    content: bytes
    content_type: str | None = None
    filename: str = ""

    if url:
        client_kwargs: dict = {}
        if httpx_timeout is not None:
            client_kwargs["timeout"] = httpx_timeout
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url, headers=url_request_headers or None)
            resp.raise_for_status()
            content = resp.content
            content_type = resp.headers.get("Content-Type")

        # 从 URL 推断文件名
        path = Path(httpx.URL(url).path)
        filename = path.name or "file"
    else:
        raw = b64_data or ""
        # 支持 data URL 形式：data:image/png;base64,xxxxxx
        if raw.startswith("data:") and ";base64," in raw:
            header, encoded = raw.split(";base64,", 1)
            # 形如 data:image/png
            mime = header[5:]
            content_type = mime or "image/png"
            content = base64.b64decode(encoded)
        else:
            content_type = "image/png"
            content = base64.b64decode(raw)

        filename = "image.png"

    # 推断扩展名和 FileType
    _, ext = os.path.splitext(filename)
    file_type = await _infer_file_type_from_content_type(content_type)
    if not ext:
        # 根据类型给一个默认后缀
        ext = ".png" if file_type == FileType.image else ".mp4"

    display_name = name or os.path.splitext(filename)[0] or filename

    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    info = await storage.upload_file(
        key=key,
        data=content,
        content_type=content_type,
        extra_args={"ACL": "public-read"},
    )

    file_id = str(uuid.uuid4())
    file_obj = FileItem(
        id=file_id,
        type=file_type,
        name=display_name,
        thumbnail=info.url,
        tags=[],
        storage_key=key,
    )
    await _add_and_flush_with_retry(session, file_obj)
    await session.refresh(file_obj)

    if usage is not None:
        from app.services.studio.file_usages import upsert_file_usage

        await upsert_file_usage(
            session,
            file_id=file_obj.id,
            project_id=usage.project_id,
            chapter_id=usage.chapter_id,
            shot_id=usage.shot_id,
            usage_kind=usage.usage_kind,
            source_ref=usage.source_ref,
        )

    return file_obj

