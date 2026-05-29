"""DINOv2 sidecar 真模型集成 smoke（W27-T1，可选）。

为什么标 ``@pytest.mark.integration``：
    - 该用例会启动一个真实的 sidecar HTTP server（要么是 ``docker compose up
      inference-dinov2``，要么是已部署的 staging 实例）；
    - 加载 ~330MB 的 DINOv2 权重，CPU 模式下首次冷启需要 5-30s；
    - 在 CI 默认收集时被 ``-m "not integration"`` 过滤掉，避免拖慢主线。

如何运行：
    .. code-block:: bash

        # 1. 起 sidecar（任选其一）：
        cd deploy/compose && docker compose up -d inference-dinov2
        # 或本机 venv 直接跑：
        cd deploy/inference-dinov2 && uvicorn app.main:app --port 8001

        # 2. 跑集成测试：
        cd backend && \\
        DINOV2_SIDECAR_BASE_URL=http://localhost:8001 \\
        uv run pytest -m integration tests/integration/test_dinov2_sidecar.py

环境变量：
    - ``DINOV2_SIDECAR_BASE_URL``：sidecar 根地址，默认
      ``http://localhost:8001``。
    - ``DINOV2_INTEGRATION_TIMEOUT_S``：单次请求超时秒数，默认 60。

断言点：
    - ``/health`` 返回 ``model_loaded=true``；
    - 同一张测试图前后两次 embed 的 cosine == 1.0（自相似性）；
    - 两张视觉接近的图片 cosine > 0.9（与任务规范的 SLO 对齐）。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import base64
import io
import os
import time

import pytest

# 该文件仅在显式开启 ``DINOV2_INTEGRATION=1`` 时才执行；默认 skip 以避免
# CI / 本地开发未起 sidecar 容器时拖累常规 pytest 跑全量。
# 配套约定保持不变：
#   - ``pytest.mark.integration`` marker 仍存在，``-m "not integration"`` 仍能过滤；
#   - 显式跑：``DINOV2_INTEGRATION=1 uv run pytest tests/integration/test_dinov2_sidecar.py``。
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DINOV2_INTEGRATION", "").lower() not in {"1", "true", "yes"},
        reason="需要外部 DINOv2 sidecar 容器；显式 export DINOV2_INTEGRATION=1 才跑",
    ),
]


def _get_base_url() -> str:
    return os.environ.get("DINOV2_SIDECAR_BASE_URL", "http://localhost:8001")


def _get_timeout_s() -> float:
    raw = os.environ.get("DINOV2_INTEGRATION_TIMEOUT_S", "60")
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 60.0


def _make_test_image_bytes(*, color: tuple[int, int, int] = (220, 60, 60)) -> bytes:
    """生成一张 224×224 的纯色 JPEG，作为可控的 embed 输入。

    DINOv2 对纯色图与稍微加噪的纯色图的 embedding 仍非常接近（cosine > 0.95），
    因此用纯色图作为"视觉相近"的最小可控样本。
    """

    pil_image = pytest.importorskip("PIL.Image", reason="PIL not installed")  # noqa: F841
    from PIL import Image  # type: ignore

    img = Image.new("RGB", (224, 224), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_noisy_test_image_bytes(*, color: tuple[int, int, int] = (220, 60, 60)) -> bytes:
    """与纯色图视觉接近的"加噪版"，断言 cosine > 0.9。"""

    pytest.importorskip("PIL.Image")
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (224, 224), color=color)
    draw = ImageDraw.Draw(img)
    # 画几条对角线扰动，但整体颜色仍接近 base 色。
    for offset in range(0, 224, 32):
        draw.line(
            (0, offset, 223, 223 - offset),
            fill=(min(255, color[0] + 10), max(0, color[1] - 5), color[2]),
            width=2,
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_sidecar_health_reports_model_loaded() -> None:
    """sidecar /health 返回 model_loaded=true（最长 60s 等待加载）。"""

    pytest.importorskip("httpx")
    import httpx

    base_url = _get_base_url()
    timeout_s = _get_timeout_s()

    deadline = time.monotonic() + timeout_s
    last_payload: dict | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{base_url}/health")
            except httpx.HTTPError:
                time.sleep(2)
                continue
            if resp.status_code == 200:
                last_payload = resp.json()
                if last_payload.get("model_loaded"):
                    break
            time.sleep(2)

    assert last_payload is not None, "sidecar /health never responded"
    assert last_payload.get("model_loaded") is True, last_payload
    assert last_payload.get("embed_dim") == 768


@pytest.mark.asyncio
async def test_sidecar_embed_self_similarity_is_one() -> None:
    """同一张图前后两次 embed 的 cosine == 1.0。"""

    pytest.importorskip("httpx")

    from app.core.integrations.dinov2.client import Dinov2HttpClient

    image_b64 = base64.b64encode(_make_test_image_bytes()).decode("ascii")

    async with Dinov2HttpClient(
        base_url=_get_base_url(),
        timeout_s=_get_timeout_s(),
        retries=2,
        retry_backoff_s=2.0,
    ) as client:
        first = await client.embed_b64(image_b64=image_b64)
        second = await client.embed_b64(image_b64=image_b64)

    assert first.dim == 768
    # 同一张图、相同模型推理：embedding 应完全一致（CPU 路径下 deterministic）。
    dot = sum(a * b for a, b in zip(first.embedding, second.embedding))
    assert dot == pytest.approx(1.0, abs=5e-3), f"cosine self={dot}"


@pytest.mark.asyncio
async def test_sidecar_similar_images_cosine_above_threshold() -> None:
    """两张视觉接近的图片：cosine > 0.9（与任务规范 SLO 对齐）。"""

    pytest.importorskip("httpx")

    from app.core.integrations.dinov2.client import Dinov2HttpClient

    a_b64 = base64.b64encode(_make_test_image_bytes()).decode("ascii")
    b_b64 = base64.b64encode(_make_noisy_test_image_bytes()).decode("ascii")

    async with Dinov2HttpClient(
        base_url=_get_base_url(),
        timeout_s=_get_timeout_s(),
        retries=2,
        retry_backoff_s=2.0,
    ) as client:
        resp = await client.similarity_b64(frame_b64=a_b64, reference_b64=b_b64)

    assert resp.similarity > 0.9, f"cosine={resp.similarity}"
