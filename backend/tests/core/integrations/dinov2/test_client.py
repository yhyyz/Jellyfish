"""DINOv2 sidecar httpx 客户端测试（W27-T1）。

测试策略：
    - 全部走 :class:`httpx.MockTransport`，不发起真实网络请求；
    - 覆盖三类路径：
        1. 200 → 正常解析 :class:`EmbedResponse` / :class:`SimilarityResponse`；
        2. 503 / 网络错误 → 退避重试（计数验证）→ 最终抛
           :class:`Dinov2SidecarUnavailable`；
        3. 4xx → 立即抛 :class:`Dinov2SidecarError`，不重试；
    - 余项：维度不匹配防御、health 探活、async with 关闭。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from app.core.contracts.visual_consistency import DINOV2_EMBED_DIM
from app.core.integrations.dinov2.client import (
    Dinov2HttpClient,
    Dinov2SidecarError,
    Dinov2SidecarUnavailable,
)


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retries: int = 2,
    retry_backoff_s: float = 0.0,
) -> Dinov2HttpClient:
    """构造一个走 MockTransport 的客户端；retry_backoff_s=0 让单测瞬时返回。"""

    transport = httpx.MockTransport(handler)
    inner = httpx.AsyncClient(transport=transport, timeout=5.0)
    return Dinov2HttpClient(
        base_url="http://inference-dinov2:8001",
        timeout_s=5.0,
        retries=retries,
        retry_backoff_s=retry_backoff_s,
        client=inner,
    )


def _mock_embed_response(elapsed_ms: int = 12) -> dict[str, Any]:
    return {
        "embedding": [0.1] * DINOV2_EMBED_DIM,
        "dim": DINOV2_EMBED_DIM,
        "elapsed_ms": elapsed_ms,
    }


# --------------------------------------------------------------------------- #
# 200 路径
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_embed_b64_returns_parsed_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_mock_embed_response())

    client = _make_client(handler)
    try:
        result = await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()

    assert captured["url"].endswith("/embed-json")
    assert captured["body"] == {"image_b64": "aGVsbG8="}
    assert len(result.embedding) == DINOV2_EMBED_DIM
    assert result.dim == DINOV2_EMBED_DIM


@pytest.mark.asyncio
async def test_embed_bytes_base64_encodes_input() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_mock_embed_response())

    client = _make_client(handler)
    try:
        await client.embed_bytes(image_bytes=b"hello-bytes")
    finally:
        await client.aclose()

    # 'hello-bytes' base64 == 'aGVsbG8tYnl0ZXM='
    assert captured["body"]["image_b64"] == "aGVsbG8tYnl0ZXM="


@pytest.mark.asyncio
async def test_similarity_returns_parsed_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"similarity": 0.92, "elapsed_ms": 18})

    client = _make_client(handler)
    try:
        result = await client.similarity_b64(frame_b64="ZnJhbWU=", reference_b64="cmVm")
    finally:
        await client.aclose()
    assert result.similarity == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_health_endpoint_returns_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "model_loaded": True,
                "device": "cpu",
                "embed_dim": DINOV2_EMBED_DIM,
            },
        )

    client = _make_client(handler)
    try:
        info = await client.health()
    finally:
        await client.aclose()
    assert info["model_loaded"] is True
    assert info["device"] == "cpu"


@pytest.mark.asyncio
async def test_async_context_manager_does_not_close_external_client() -> None:
    """传入外部 :class:`httpx.AsyncClient` 时，``__aexit__`` 不主动 close。

    契约：调用方对自己构造的 client 负责，避免双关闭引发的 RuntimeError。
    本类只在自己 owned client 时调 aclose。
    """

    closed = {"value": False}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_mock_embed_response())

    transport = httpx.MockTransport(handler)
    inner = httpx.AsyncClient(transport=transport, timeout=5.0)

    real_aclose = inner.aclose

    async def _wrapped_aclose() -> None:
        closed["value"] = True
        await real_aclose()

    inner.aclose = _wrapped_aclose  # type: ignore[assignment]

    async with Dinov2HttpClient(
        base_url="http://inference-dinov2:8001",
        client=inner,
    ) as client:
        await client.embed_b64(image_b64="aGVsbG8=")

    assert closed["value"] is False
    await inner.aclose()
    assert closed["value"] is True


@pytest.mark.asyncio
async def test_async_context_manager_closes_owned_client() -> None:
    """未注入 client 时（owned），``__aexit__`` 主动 close 底层连接池。"""

    closed_calls = {"count": 0}

    async with Dinov2HttpClient(base_url="http://inference-dinov2:8001") as client:
        # 直接 patch 它持有的内部 client，绕过真实网络。
        real_aclose = client._client.aclose  # type: ignore[attr-defined]

        async def _wrapped_aclose() -> None:
            closed_calls["count"] += 1
            await real_aclose()

        client._client.aclose = _wrapped_aclose  # type: ignore[attr-defined]

    assert closed_calls["count"] == 1


# --------------------------------------------------------------------------- #
# 503 / 网络错误重试
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_503_response_retries_then_succeeds() -> None:
    state = {"calls": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 3:
            return httpx.Response(503, json={"detail": "model loading"})
        return httpx.Response(200, json=_mock_embed_response())

    client = _make_client(handler, retries=3)
    try:
        await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()

    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_503_persistent_raises_unavailable_after_retries() -> None:
    state = {"calls": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503, json={"detail": "still loading"})

    client = _make_client(handler, retries=2)
    try:
        with pytest.raises(Dinov2SidecarUnavailable):
            await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()

    # retries=2 ⇒ 总共 1 次首发 + 2 次重试 = 3 次。
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_connect_error_retries_then_raises() -> None:
    state = {"calls": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        raise httpx.ConnectError("simulated connect failure")

    client = _make_client(handler, retries=1)
    try:
        with pytest.raises(Dinov2SidecarUnavailable):
            await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()
    assert state["calls"] == 2


# --------------------------------------------------------------------------- #
# 4xx 业务错误
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_422_raises_sidecar_error_without_retry() -> None:
    state = {"calls": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(422, json={"detail": "invalid base64"})

    client = _make_client(handler, retries=3)
    try:
        with pytest.raises(Dinov2SidecarError):
            await client.embed_b64(image_b64="!!!not-base64!!!")
    finally:
        await client.aclose()
    assert state["calls"] == 1


# --------------------------------------------------------------------------- #
# 维度防御
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dimension_mismatch_raises_sidecar_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "embedding": [0.1] * 256,
                "dim": 256,
                "elapsed_ms": 10,
            },
        )

    client = _make_client(handler)
    try:
        with pytest.raises(Dinov2SidecarError):
            await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_invalid_json_response_raises_sidecar_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = _make_client(handler)
    try:
        with pytest.raises(Dinov2SidecarError):
            await client.embed_b64(image_b64="aGVsbG8=")
    finally:
        await client.aclose()
