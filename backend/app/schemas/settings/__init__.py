"""``settings.*`` schemas namespace。

P4 Wave A 引入「`/api/v1/settings/*` 管理面板」分组，专门承载与运营/
运维相关的 admin 配置入口（API key 配额、第三方供应商凭据等）。当前
仅暴露 :mod:`app.schemas.settings.api_key`；后续 wave 若新增供应商
凭据、Webhook 配置等读写 schemas 也会落到本目录。
"""

from app.schemas.settings.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreated,
    ApiKeyHashRequest,
    ApiKeyRead,
    ApiKeyUsageRead,
)

__all__ = [
    "ApiKeyCreateRequest",
    "ApiKeyCreated",
    "ApiKeyHashRequest",
    "ApiKeyRead",
    "ApiKeyUsageRead",
]
