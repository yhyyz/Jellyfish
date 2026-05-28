"""``POST /api/v1/commerce/outcomes/import`` 路由（W22-T2，P4 Wave B 1/11）。

P4 Wave B 1/11：投放数据回灌的 CSV 上传通道。

按 ``AGENTS.md`` 第 4 条保持 route 层瘦身：

- 收 ``multipart/form-data``：``file`` 字段（必填）+ ``mapping_profile``
  字段（可选）。
- 在调 service 之前**提前**做 5MB 大小校验：通过解析 ``content-length``
  header（缺失或为 0 时跳过预检），并由 service 在流式 read 时再做一
  次硬限位（防伪造 header）。
- 把执行委托给 :class:`OutcomeCsvImporter`，路由只做响应壳包装。

为什么允许"前置 + 流式"双重 5MB 检查：
    HTTP header 可被伪造，但很多正常请求都带正确的 ``content-length``，
    在路由入口先 reject 可避免把 5GB 的恶意上传完整接收一遍再丢弃。
    流式 reader 同时也会在累计读取超过 5MB 时主动 raise，防止 header
    被绕过。
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.outcome_csv import ImportSummary
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.outcome_csv_importer import OutcomeCsvImporter

router = APIRouter()


# 5MB 上限。stdlib csv 解析在该体量下完全够用，且能避免恶意大文件耗尽
# 容器内存。需要更大配额时应另做"分片上传 + 后台任务"方案。
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _enforce_size_limit(request: Request) -> None:
    """根据 ``Content-Length`` header 做前置体积检查。

    缺失或为 0 时跳过——FastAPI/uvicorn 在 chunked transfer 下可能不
    暴露该 header。底层 importer 仍会在流式读取时硬性截断。
    """
    raw = request.headers.get("content-length")
    if not raw:
        return
    try:
        size = int(raw)
    except ValueError:
        return
    if size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file size {size} exceeds 5MB limit",
        )


class _CappedReadStream(io.RawIOBase):
    """包装 ``UploadFile.file``，在累计读取超过 5MB 时主动 raise。

    SpooledTemporaryFile 默认会先在内存里缓存数据；这里再加一道闸门，
    避免上游伪造 ``content-length`` header 绕过路由侧检查。继承
    :class:`io.RawIOBase` 让 ``TextIOWrapper`` / ``csv`` 模块期望的全
    部属性（``closed`` / ``readable`` / ``writable`` / ``seekable``）
    都通过基类默认实现满足。
    """

    def __init__(self, raw, limit: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._raw = raw
        self._limit = limit
        self._consumed = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[no-untyped-def]
        chunk = self._raw.read(len(b))
        if not chunk:
            return 0
        self._consumed += len(chunk)
        if self._consumed > self._limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="file body exceeds 5MB limit",
            )
        n = len(chunk)
        b[:n] = chunk
        return n


@router.post(
    "/outcomes/import",
    response_model=ApiResponse[ImportSummary],
    status_code=status.HTTP_200_OK,
    summary="批量导入投放效果 CSV（5MB 上限，单行失败不中断）",
)
async def import_outcomes_csv(
    request: Request,
    file: UploadFile = File(..., description="UTF-8 CSV 文件，含 header 行"),
    mapping_profile: str = Form(
        "default",
        description="列名映射 profile：douyin / xiaohongshu / default",
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ImportSummary]:
    """以 multipart 接收 CSV，按 mapping profile 流式导入。

    Args:
        request: 用于读取 ``Content-Length`` 做前置 5MB 校验。
        file: 上传的 CSV 文件；UTF-8 编码（兼容 BOM）。
        mapping_profile: ``douyin`` / ``xiaohongshu`` / ``default``，
            未知值回退 ``default``。
        db: 由 ``get_db`` 注入的异步会话。

    Returns:
        ``ApiResponse[ImportSummary]``。即便有失败行也返回 200，让前端
        能拿到 ``inserted`` / ``failed`` / ``errors`` 三段信息。

    Raises:
        HTTPException: 413 当文件超过 5MB；400 当文件名后缀不是 csv。
    """
    _enforce_size_limit(request)
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only .csv files are supported",
        )

    capped = _CappedReadStream(file.file, _MAX_UPLOAD_BYTES)
    importer = OutcomeCsvImporter(db, mapping_profile=mapping_profile)
    summary = await importer.import_stream(capped)
    return success_response(summary)


__all__ = ["router"]
