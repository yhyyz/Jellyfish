"""平台导出 worker（W23-T2，P4 Wave B）。

为什么存在
----------

P4 Wave B 起 ``commerce/*`` 链路新增"平台导出"能力：把已经合成好的章节
成片（``chapter_av_export`` 产出 mp4，``FileUsageKind.chapter_master_dubbed``）
按 :class:`PlatformExportPreset` 转换为不同平台的发布版本（如抖音 9:16
默认 / TikTok 默认 / 小红书 1:1 等）。

与 ``chapter_av_export`` 的关系
-------------------------------

- ``chapter_av_export`` 是"主合成"：跨路径合成 + 字幕烧录 + 响度归一化，
  产出"原始成片"，每个章节通常只跑一次；
- ``commerce_export`` 是"二次衍生"：基于已经合成好的章节成片，按平台预设
  做画幅 / 编码 / 水印 / 贴纸 / 响度等差异化转换，每个 (variant, preset)
  组合都会跑一次，因此本 worker 不重复 chapter_av_export 的字幕烧录主链。

设计要点
--------

- 输入：``run_args = {"variant_id": str, "preset_id": str}``。
- 步骤：
  1. 反查 :class:`StoryVariant` → 拿到 ``project_id`` / ``chapter_id``。
  2. 反查最新的 :class:`FileUsage` ``chapter_master_dubbed`` 行，定位章节
     成片 ``FileItem``。
  3. 反查 :class:`PlatformExportPreset` → 装配 ffmpeg 参数（委托给
     :mod:`app.services.commerce.ffmpeg_preset_transform`）。
  4. 下载源 mp4 + 水印 + 各贴纸到临时目录。
  5. 子进程跑 ffmpeg，输出到临时文件。
  6. 上传到 minio + 落 :class:`FileItem` 行（``usage_kind=product_export``）
     + 反查 :class:`GenerationTaskLink` 回写 ``file_id`` + 落 :class:`FileUsage`
     行链接到 ``(variant_id, preset_id)``（``source_ref`` 编码两者）。
- 队列：``slow``，1800s 超时（与 chapter_av_export 同档）。

异常路径与 hotfix-4 canonical 模板对齐：``set_status(running)`` → 业务 →
``set_result`` → ``set_status(succeeded)``；失败时 rollback + 独立会话写
``failed``。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.platform_export_preset import PlatformExportPreset
from app.models.story_formula import StoryVariant
from app.models.studio import FileItem, FileType, FileUsage
from app.models.task_links import GenerationTaskLink
from app.models.types import FileUsageKind
from app.services.commerce.ffmpeg_preset_transform import (
    StickerInput,
    build_preset_transform_plan,
    stickers_from_specs,
)
from app.services.studio.file_usages import upsert_file_usage
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "commerce_export"
"""注册键：与 ``task_dispatch.TASK_KIND_COMMERCE_EXPORT`` 同源。"""

DEFAULT_TIMEOUT_SECONDS = 1800.0
"""默认超时（秒）：与 chapter_av_export 同档（3-10 分钟级，1800s 留 3x 余量）。"""

_RUNNING_PROGRESS = 5
_LOAD_PROGRESS = 20
_FFMPEG_DONE_PROGRESS = 80
_SUCCEEDED_PROGRESS = 100

_OUTPUT_PREFIX = "generated-videos/commerce-export"
"""产物对象存储 key 前缀，与 chapter_av_export 显式分离便于排查。"""


def _coerce_str(value: object) -> str:
    """安全规范化字符串入参（去首尾空白）。"""

    if value is None:
        return ""
    return str(value).strip()


async def _resolve_chapter_master_file(
    session: AsyncSession,
    *,
    chapter_id: str,
) -> FileItem:
    """反查章节最新的 chapter_master_dubbed 文件；缺失则抛 RuntimeError。"""

    stmt = (
        select(FileItem)
        .join(FileUsage, FileUsage.file_id == FileItem.id)
        .where(
            FileUsage.chapter_id == chapter_id,
            FileUsage.usage_kind == FileUsageKind.chapter_master_dubbed.value,
        )
        .order_by(FileItem.updated_at.desc())
        .limit(1)
    )
    file_obj = (await session.execute(stmt)).scalars().first()
    if file_obj is None or not file_obj.storage_key:
        raise RuntimeError(
            f"章节 {chapter_id!r} 缺少 chapter_av_export 产物（chapter_master_dubbed），"
            "请先完成章节级 AV 合成"
        )
    return file_obj


async def _download_to(
    file_obj: FileItem,
    *,
    dest: Path,
    label: str,
) -> Path:
    """下载单个 FileItem 内容到本地 dest；空文件抛 RuntimeError。"""

    if file_obj is None or not file_obj.storage_key:
        raise RuntimeError(f"{label} 缺少 FileItem 或 storage_key")
    data = await storage.download_file(key=file_obj.storage_key)
    if not data:
        raise RuntimeError(f"{label} 下载结果为空: {file_obj.id}")
    dest.write_bytes(data)
    return dest


async def _resolve_overlay_assets(
    session: AsyncSession,
    *,
    preset: PlatformExportPreset,
    tmp_path: Path,
) -> tuple[str | None, list[StickerInput]]:
    """下载 preset 引用的水印 + 贴纸到本地，返回 (水印路径, 贴纸列表)。

    缺失的贴纸条目会被 :py:func:`stickers_from_specs` 静默丢弃，避免一条
    脏数据炸掉整次导出；水印缺失则直接退化为不打水印（preset 的水印是
    可选项，删除水印文件不应阻塞已存在的预设）。
    """

    watermark_local: str | None = None
    if preset.watermark_file_id:
        wm = await session.get(FileItem, preset.watermark_file_id)
        if wm is not None and wm.storage_key:
            wm_path = tmp_path / f"watermark_{uuid.uuid4().hex[:8]}{Path(wm.storage_key).suffix or '.png'}"
            await _download_to(wm, dest=wm_path, label="watermark")
            watermark_local = str(wm_path)

    file_id_to_local: dict[str, str] = {}
    for spec in (preset.sticker_specs or []):
        file_id = str(spec.get("file_id") or "").strip()
        if not file_id or file_id in file_id_to_local:
            continue
        sticker = await session.get(FileItem, file_id)
        if sticker is None or not sticker.storage_key:
            continue
        st_path = tmp_path / f"sticker_{file_id}{Path(sticker.storage_key).suffix or '.png'}"
        await _download_to(sticker, dest=st_path, label=f"sticker {file_id}")
        file_id_to_local[file_id] = str(st_path)

    sticker_inputs = stickers_from_specs(
        preset.sticker_specs or [],
        file_id_to_local_path=file_id_to_local,
    )
    return watermark_local, sticker_inputs


async def _run_ffmpeg(args: list[str]) -> None:
    """启动 ffmpeg 子进程并等待结束；失败时把 stderr 收尾错误抛出。"""

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"ffmpeg commerce_export 失败: {msg}")


async def run_commerce_export_task(task_id: str, run_args: dict[str, Any]) -> None:
    """异步 runner：把章节成片按预设转换为平台版本。

    异常处理：
        与 ``chapter_av_export_task`` 同模板：try 中 rollback、独立会话写
        ``failed``、再向上抛由 :class:`AbstractAsyncDelegatingExecutor`
        转换为 Celery 失败状态。
    """

    variant_id = _coerce_str(run_args.get("variant_id"))
    preset_id = _coerce_str(run_args.get("preset_id"))
    if not variant_id:
        raise RuntimeError("run_args 缺少 variant_id")
    if not preset_id:
        raise RuntimeError("run_args 缺少 preset_id")

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "running",
                variant_id=variant_id,
                preset_id=preset_id,
            )

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_load")
                return

            variant = await session.get(StoryVariant, variant_id)
            if variant is None:
                raise RuntimeError(f"StoryVariant 不存在: {variant_id}")

            preset = await session.get(PlatformExportPreset, preset_id)
            if preset is None:
                raise RuntimeError(f"PlatformExportPreset 不存在: {preset_id}")

            source_file = await _resolve_chapter_master_file(
                session, chapter_id=variant.chapter_id
            )

            await store.set_progress(task_id, _LOAD_PROGRESS)
            await session.commit()

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_load")
                return

            with tempfile.TemporaryDirectory(
                prefix=f"jf-commerce-export-{task_id}-"
            ) as tmp:
                tmp_path = Path(tmp)
                source_local = tmp_path / "source.mp4"
                await _download_to(source_file, dest=source_local, label="章节成片")

                watermark_local, sticker_inputs = await _resolve_overlay_assets(
                    session, preset=preset, tmp_path=tmp_path
                )

                plan = build_preset_transform_plan(
                    preset,
                    source_video_path=str(source_local),
                    watermark_local_path=watermark_local,
                    sticker_inputs=sticker_inputs,
                )

                ext = (preset.file_format or "mp4").lower()
                output_local = tmp_path / f"export.{ext}"
                args = plan.to_ffmpeg_args(str(output_local))
                await _run_ffmpeg(args)

                output_bytes = output_local.read_bytes()
                if not output_bytes:
                    raise RuntimeError("commerce_export 输出为空文件")

            await store.set_progress(task_id, _FFMPEG_DONE_PROGRESS)

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_ffmpeg")
                return

            content_type = "video/mp4" if ext == "mp4" else f"video/{ext}"
            out_key = (
                f"{_OUTPUT_PREFIX}/{variant_id}/{preset_id}/{uuid.uuid4().hex}.{ext}"
            )
            info = await storage.upload_file(
                key=out_key,
                data=output_bytes,
                content_type=content_type,
                extra_args={"ACL": "public-read"},
            )

            new_file_id = uuid.uuid4().hex
            session.add(
                FileItem(
                    id=new_file_id,
                    type=FileType.video,
                    name=f"export-{variant_id}-{preset_id}",
                    thumbnail=info.url,
                    tags=["commerce_export", preset.platform.value if hasattr(preset.platform, "value") else str(preset.platform)],
                    storage_key=out_key,
                ),
            )

            link_stmt = (
                select(GenerationTaskLink)
                .where(GenerationTaskLink.task_id == task_id)
                .limit(1)
            )
            link_row = (await session.execute(link_stmt)).scalars().first()
            if link_row is not None:
                link_row.file_id = new_file_id

            await upsert_file_usage(
                session,
                file_id=new_file_id,
                project_id=variant.project_id,
                chapter_id=variant.chapter_id,
                shot_id=None,
                usage_kind=FileUsageKind.product_export,
                source_ref=f"variant:{variant_id}:preset:{preset_id}:task:{task_id}",
            )

            await store.set_result(
                task_id,
                {
                    "file_id": new_file_id,
                    "variant_id": variant_id,
                    "preset_id": preset_id,
                    "platform": (
                        preset.platform.value
                        if hasattr(preset.platform, "value")
                        else str(preset.platform)
                    ),
                    "aspect_ratio": preset.aspect_ratio,
                    "file_format": preset.file_format,
                    "codec_preset": preset.codec_preset,
                    "loudness_lufs": float(preset.loudness_lufs),
                    "storage_key": out_key,
                },
            )

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_persist")
                return

            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                variant_id=variant_id,
                preset_id=preset_id,
                file_id=new_file_id,
            )
        except Exception as exc:  # noqa: BLE001 - 与既有 worker 模板保持一致
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


def build_commerce_export_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 commerce_export 执行器实例。

    Returns:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，
        ``task_kind = commerce_export``，``timeout_seconds = 1800``。
    """

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_commerce_export_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_commerce_export_executor",
    "run_commerce_export_task",
]
