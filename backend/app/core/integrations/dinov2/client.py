"""DINOv2 sidecar HTTP 客户端（P4 W27-T1）。

为什么存在：
    backend 主镜像不打包 torch / transformers（DECISION D-VISION-DEPLOY=sidecar），
    本类负责把 :class:`EmbedRequest` / :class:`SimilarityRequest` 通过 httpx
    送给独立 sidecar 服务（``deploy/inference-dinov2``），并把响应反序列化为
    契约层的 :class:`EmbedResponse` / :class:`SimilarityResponse`。

设计要点：
    - 使用 :class:`httpx.AsyncClient`，沿用既有 integrations 的 async 风格；
    - 重试策略：仅对 503 / 网络层错误退避重试（与 sidecar /health 的就绪
      模型语义一致，503 = "尚未加载完成，请重试"）；4xx 不重试；
    - timeout / retries / backoff 全部从 :data:`app.config.settings` 读取，
      可由 .env 覆盖；
    - **不**直接抛 :class:`httpx.HTTPError` 给上层：包装为
      :class:`Dinov2SidecarUnavailable`（503/网络）/ :class:`Dinov2SidecarError`
      （4xx 业务错误），让 worker 层做语义化降级（→ score=null + reason）。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from app.core.contracts.visual_consistency import (
    DINOV2_EMBED_DIM,
    EmbedResponse,
    SimilarityResponse,
)


logger = logging.getLogger(__name__)


class Dinov2SidecarError(RuntimeError):
    """sidecar 返回 4xx 业务错误（输入非法、图片解码失败等）。

    上层不应重试；通常意味着调用参数出了问题。
    """


class Dinov2SidecarUnavailable(RuntimeError):
    """sidecar 不可达（503 / 网络层错误 / 超时）。

    上层（worker）应把对应 shot 的 ``consistency_score`` 写为 ``None``，
    reason 标 ``sidecar_unavailable``，避免阻塞主流程。
    """


class Dinov2HttpClient:
    """DINOv2 sidecar 的 httpx 客户端封装。

    使用方式（推荐 async with，自动释放底层 connection pool）：

    .. code-block:: python

        async with Dinov2HttpClient(base_url="http://inference-dinov2:8001") as client:
            resp = await client.embed_b64(image_b64=...)
            print(resp.embedding)
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float = 30.0,
        retries: int = 3,
        retry_backoff_s: float = 1.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """构造客户端。

        Args:
            base_url: sidecar 根地址，如 ``http://inference-dinov2:8001``。
            timeout_s: 单次 HTTP 调用超时；不含重试间隔。
            retries: 503 / 网络错误时的重试次数（不含首次调用）。
            retry_backoff_s: 指数退避基数；第 N 次等待
                ``retry_backoff_s * (2 ** (N-1))`` 秒。
            client: 可选已构造的 :class:`httpx.AsyncClient`；测试时注入
                ``MockTransport`` 方便不发起真实网络请求。
        """

        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._retries = max(0, retries)
        self._retry_backoff_s = max(0.0, retry_backoff_s)
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def __aenter__(self) -> "Dinov2HttpClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层连接池；外部传入 client 时不主动 close（避免双关）。"""

        if self._owned_client:
            await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        """探活：直接返回 sidecar 端 ``/health`` 的 JSON。

        不重试：调用方就是为了判断"现在是否就绪"，重试反而会掩盖未就绪状态。
        """

        url = f"{self._base_url}/health"
        try:
            resp = await self._client.get(url, timeout=self._timeout_s)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise Dinov2SidecarUnavailable(f"health check failed: {exc}") from exc
        return resp.json()

    async def embed_bytes(self, *, image_bytes: bytes) -> EmbedResponse:
        """对单张图片字节做嵌入。

        内部把字节做 base64 后调 ``/embed-json`` 端点（避免 multipart
        构造的样板代码与 transport 的 cookie/redirect 扰动）。
        """

        if not image_bytes:
            raise ValueError("image_bytes is empty")
        return await self.embed_b64(image_b64=base64.b64encode(image_bytes).decode("ascii"))

    async def embed_b64(self, *, image_b64: str) -> EmbedResponse:
        """对 base64 编码的图片做嵌入。

        ``image_b64`` 可带 ``data:image/...;base64,`` 前缀；sidecar 内部会剥离。
        """

        url = f"{self._base_url}/embed-json"
        payload = {"image_b64": image_b64}
        data = await self._post_json_with_retry(url, payload)
        embed = EmbedResponse.model_validate(data)
        if embed.dim != DINOV2_EMBED_DIM:
            raise Dinov2SidecarError(
                f"unexpected embed dim from sidecar: got {embed.dim}, expected {DINOV2_EMBED_DIM}"
            )
        return embed

    async def similarity_b64(
        self, *, frame_b64: str, reference_b64: str
    ) -> SimilarityResponse:
        """直接计算两张图片的 cosine similarity。"""

        url = f"{self._base_url}/similarity"
        payload = {"frame_b64": frame_b64, "reference_b64": reference_b64}
        data = await self._post_json_with_retry(url, payload)
        return SimilarityResponse.model_validate(data)

    # --------------------------------------------------------------------- #
    # 内部：带重试的 JSON POST
    # --------------------------------------------------------------------- #

    async def _post_json_with_retry(
        self, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """重试策略：

            - 503 + 连接错误 + 读超时 → 退避重试（最多 ``retries`` 次）；
            - 4xx（非 503） → 立即抛 :class:`Dinov2SidecarError`，不重试；
            - 5xx（非 503） → 按服务端临时故障处理，退避重试。

        Returns:
            响应体的 JSON dict。
        """

        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.post(
                    url, json=payload, timeout=self._timeout_s
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                logger.warning(
                    "dinov2 sidecar transport error url=%s attempt=%d/%d: %s",
                    url,
                    attempt + 1,
                    self._retries + 1,
                    exc,
                )
            except httpx.HTTPError as exc:
                # 其他 httpx 错误（解码 / 协议）一般不可重试。
                raise Dinov2SidecarUnavailable(
                    f"sidecar transport failure: {exc}"
                ) from exc
            else:
                if resp.status_code < 400:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise Dinov2SidecarError(
                            f"invalid JSON from sidecar: {exc}"
                        ) from exc

                if resp.status_code in (502, 503, 504) or 500 <= resp.status_code < 600:
                    # 服务端临时故障：退避重试。
                    last_exc = Dinov2SidecarUnavailable(
                        f"sidecar returned {resp.status_code}: {_safe_text(resp)}"
                    )
                    logger.warning(
                        "dinov2 sidecar 5xx url=%s status=%d attempt=%d/%d",
                        url,
                        resp.status_code,
                        attempt + 1,
                        self._retries + 1,
                    )
                else:
                    # 4xx：立即抛业务错误，不重试。
                    raise Dinov2SidecarError(
                        f"sidecar returned {resp.status_code}: {_safe_text(resp)}"
                    )

            if attempt < self._retries:
                await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))

        assert last_exc is not None
        if isinstance(last_exc, Dinov2SidecarUnavailable):
            raise last_exc
        raise Dinov2SidecarUnavailable(
            f"sidecar unreachable after {self._retries + 1} attempts: {last_exc}"
        ) from last_exc


def _safe_text(resp: httpx.Response) -> str:
    """截断响应体，避免错误日志爆炸。"""

    try:
        body = resp.text
    except Exception:  # noqa: BLE001
        return ""
    return body[:500]


def build_default_dinov2_client() -> Dinov2HttpClient:
    """从 :data:`app.config.settings` 构造默认 client。

    每次调用产生独立 :class:`httpx.AsyncClient`；调用方需自己 ``async with``
    管理生命周期。
    """

    # 局部 import 防止 contracts 层意外被 settings 反向依赖。
    from app.config import settings

    return Dinov2HttpClient(
        base_url=settings.dinov2_sidecar_base_url,
        timeout_s=settings.dinov2_sidecar_timeout_s,
        retries=settings.dinov2_sidecar_retries,
        retry_backoff_s=settings.dinov2_sidecar_retry_backoff_s,
    )


__all__ = [
    "Dinov2HttpClient",
    "Dinov2SidecarError",
    "Dinov2SidecarUnavailable",
    "build_default_dinov2_client",
]
