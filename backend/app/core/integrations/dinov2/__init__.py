"""DINOv2 sidecar 客户端（P4 W27-T1）。

为什么独立一个包：
    - 沿用 ``app.core.integrations.{aliyun,openai,volcengine}`` 的目录约定，
      把"对外部 ML / 第三方服务的 HTTP/SDK 适配"集中收口；
    - 主 backend 镜像里只有 httpx，**完全不引入 torch / transformers**
      （DECISION D-VISION-DEPLOY=sidecar）。

入口类：
    - :class:`Dinov2HttpClient`：``async with`` 风格使用，封装 /embed
      与 /similarity，含简单指数退避重试。
"""

from app.core.integrations.dinov2.client import (
    Dinov2HttpClient,
    Dinov2SidecarError,
    Dinov2SidecarUnavailable,
    build_default_dinov2_client,
)

__all__ = [
    "Dinov2HttpClient",
    "Dinov2SidecarError",
    "Dinov2SidecarUnavailable",
    "build_default_dinov2_client",
]
