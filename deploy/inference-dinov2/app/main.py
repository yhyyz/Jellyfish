"""DINOv2 视觉一致性 sidecar FastAPI 入口（P4 W27-T1）。

提供三个端点：
    - ``GET  /health``      —— 进程存活 + 模型是否就绪；
    - ``POST /embed``       —— 图片（multipart 文件 / form url / JSON base64）→ 768-dim embedding；
    - ``POST /similarity``  —— 两段 base64 图片 → 余弦相似度（0-1）。

设计要点：
    - 主 backend 通过 :mod:`app.core.integrations.dinov2.client` 走 httpx 调用本服务；
    - sidecar 仅暴露在 docker network 内（compose 中 ports 仅暴露给本机）；
    - 启动期通过 lifespan 触发 :class:`Dinov2Embedder.ensure_loaded`，避免首请求超时；
    - 失败语义：模型不可用 → 503，输入非法 → 422，未知错误 → 500。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.model import Dinov2Embedder, cosine_similarity

logger = logging.getLogger(__name__)

# 单进程全局单例：通过 lifespan 注入 / 释放。
_embedder: Dinov2Embedder | None = None


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动期触发模型加载，关闭期释放引用。

    DINOv2-base ~330MB；首次加载在 CPU 上约 5-10s，命中 HF cache 后 < 2s。
    模型加载在子线程执行，避免阻塞 uvicorn 的 startup 事件循环。
    """

    global _embedder  # noqa: PLW0603
    _embedder = Dinov2Embedder()
    started = time.monotonic()
    try:
        # transformers 的 from_pretrained 是同步阻塞 IO + CPU，挪到默认线程池。
        await asyncio.get_running_loop().run_in_executor(None, _embedder.ensure_loaded)
        logger.info(
            "dinov2 sidecar ready elapsed_ms=%d device=%s",
            int((time.monotonic() - started) * 1000),
            _embedder.device,
        )
    except Exception as exc:  # noqa: BLE001
        # 容器编排会自动重启失败的容器；显式记录避免静默卡死。
        logger.exception("dinov2 sidecar failed to load model: %s", exc)
    yield
    _embedder = None


app = FastAPI(
    title="Jellyfish DINOv2 Visual Consistency Sidecar",
    version="0.1.0",
    lifespan=_lifespan,
)


def _require_embedder() -> Dinov2Embedder:
    """获取已加载的全局 embedder；未就绪时抛 503。

    503 比 500 更适合：客户端可基于 Retry-After 简单退避重试，
    而 500 通常意味着不可恢复错误。
    """

    if _embedder is None or not _embedder.is_loaded:
        raise HTTPException(status_code=503, detail="DINOv2 model is not ready")
    return _embedder


# --------------------------------------------------------------------------- #
# 数据契约（与 backend/app/core/contracts/visual_consistency.py 字段一一对齐）
# --------------------------------------------------------------------------- #


class EmbedJsonRequest(BaseModel):
    """JSON 形式的 embed 请求。

    支持两种二选一的图片来源：
        - ``image_b64``：base64 编码的图片字节（建议用于 backend 调用，避免
          多 hop 文件传输）；
        - ``image_url``：可被 sidecar 进程直接 GET 的 URL（用于本机调试）。
    """

    image_b64: str | None = Field(default=None, description="base64 编码图片")
    image_url: str | None = Field(default=None, description="可访问的图片 URL")


class EmbedResponse(BaseModel):
    embedding: list[float] = Field(..., description="DINOv2 ViT-B/14 cls embedding（已 L2 归一）")
    dim: int = Field(..., description="向量维度（固定 768）")
    elapsed_ms: int = Field(..., description="本次推理耗时毫秒")


class SimilarityRequest(BaseModel):
    frame_b64: str = Field(..., description="base64 编码的视频帧图片")
    reference_b64: str = Field(..., description="base64 编码的参考资产图片")


class SimilarityResponse(BaseModel):
    similarity: float = Field(..., description="cosine similarity，[-1, 1]")
    elapsed_ms: int = Field(..., description="本次推理耗时毫秒")


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    embed_dim: int


# --------------------------------------------------------------------------- #
# 工具：图片来源解析
# --------------------------------------------------------------------------- #


def _decode_b64(payload: str) -> bytes:
    """把可能带 data URL prefix 的 base64 字符串解码为字节。

    形如 ``data:image/png;base64,xxx`` 的 prefix 会被剥离；非法 base64
    抛 422，由 FastAPI 包装成统一错误响应。
    """

    if not payload:
        raise HTTPException(status_code=422, detail="image_b64 is empty")
    if "," in payload and payload.lstrip().startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc


async def _fetch_url(url: str) -> bytes:
    """拉取远程 URL 返回字节。

    超时 10s 与 P4 默认 worker 超时（600s）成 60x 安全比。
    """

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=422, detail=f"failed to fetch image_url: {exc}") from exc


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """轻量健康检查。

    存活路径下永远返回 200；模型尚未加载时 ``model_loaded=false``，
    docker HEALTHCHECK 仍判活（容器进程没死），但调用方会拿到 503。
    """

    if _embedder is None:
        return HealthResponse(
            status="starting",
            model_loaded=False,
            device="unknown",
            embed_dim=0,
        )
    return HealthResponse(
        status="ok" if _embedder.is_loaded else "starting",
        model_loaded=_embedder.is_loaded,
        device=_embedder.device,
        embed_dim=_embedder.embed_dim,
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed_endpoint(
    file: UploadFile | None = File(default=None),
    image_url: str | None = Form(default=None),
    image_b64: str | None = Form(default=None),
) -> EmbedResponse:
    """对单张图片做嵌入。

    支持三种入参（按优先级解析）：
        1. ``multipart/form-data`` 文件字段 ``file``；
        2. ``form`` 字段 ``image_b64``（base64 字符串，可带 data URL prefix）；
        3. ``form`` 字段 ``image_url``（仅 sidecar 内网可达 URL）。

    任何一种都需先经过 ``_require_embedder()`` 检查模型已就绪。
    """

    embedder = _require_embedder()
    started = time.monotonic()

    if file is not None and file.filename:
        image_bytes = await file.read()
    elif image_b64:
        image_bytes = _decode_b64(image_b64)
    elif image_url:
        image_bytes = await _fetch_url(image_url)
    else:
        raise HTTPException(
            status_code=422,
            detail="one of file / image_b64 / image_url is required",
        )

    if not image_bytes:
        raise HTTPException(status_code=422, detail="image bytes are empty")

    try:
        # PyTorch 推理是 CPU/GPU 阻塞；放线程池避免阻塞事件循环。
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, embedder.embed_image, image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return EmbedResponse(
        embedding=vector,
        dim=embedder.embed_dim,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


@app.post("/embed-json", response_model=EmbedResponse)
async def embed_json_endpoint(payload: EmbedJsonRequest) -> EmbedResponse:
    """JSON 路径的 ``/embed``，用于不便走 multipart 的客户端。"""

    embedder = _require_embedder()
    started = time.monotonic()

    if payload.image_b64:
        image_bytes = _decode_b64(payload.image_b64)
    elif payload.image_url:
        image_bytes = await _fetch_url(payload.image_url)
    else:
        raise HTTPException(
            status_code=422,
            detail="one of image_b64 / image_url is required",
        )

    try:
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, embedder.embed_image, image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return EmbedResponse(
        embedding=vector,
        dim=embedder.embed_dim,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


@app.post("/similarity", response_model=SimilarityResponse)
async def similarity_endpoint(payload: SimilarityRequest) -> SimilarityResponse:
    """对两张图片直接计算 cosine similarity，省掉外部一次往返。

    内部仍然顺序计算两次 embedding，再做点积；仅省去 backend 多次调
    /embed 的 HTTP overhead。
    """

    embedder = _require_embedder()
    started = time.monotonic()

    frame_bytes = _decode_b64(payload.frame_b64)
    reference_bytes = _decode_b64(payload.reference_b64)

    loop = asyncio.get_running_loop()
    try:
        # 顺序计算：DINOv2-base 单帧 ~50ms（GPU）/ ~500ms（CPU），
        # 串行执行简单且不会与单进程模型互斥锁竞争。
        frame_vec = await loop.run_in_executor(None, embedder.embed_image, frame_bytes)
        reference_vec = await loop.run_in_executor(None, embedder.embed_image, reference_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    sim = cosine_similarity(frame_vec, reference_vec)
    return SimilarityResponse(
        similarity=sim,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# pylint: disable=unused-argument
@app.exception_handler(Exception)
async def _generic_exception_handler(_request: Any, exc: Exception) -> Any:
    """统一 500 错误响应文案，避免泄露 stack trace。"""

    from fastapi.responses import JSONResponse  # 局部 import 防止循环
    logger.exception("dinov2 sidecar internal error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal sidecar error"})


__all__ = ["app"]
