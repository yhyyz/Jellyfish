"""API key 管理面板的 Pydantic schemas（P4 W24-T1）。

本模块对应 :class:`app.models.api_quota.ApiKeyQuota`，承担 ``/api/v1/
settings/api-keys`` 管理面板的读写 DTO：

- :class:`ApiKeyCreateRequest` —— 创建 key 时的表单参数；
- :class:`ApiKeyCreated` —— 创建成功的**一次性**响应（plaintext 明文
  仅在此 DTO 出现；后续 GET/列表接口永远只返回 hash）；
- :class:`ApiKeyHashRequest` —— ``revoke`` / ``usage`` 等以 hash 为
  唯一键的 POST body；
- :class:`ApiKeyRead` —— 列表 / 详情读视图；
- :class:`ApiKeyUsageRead` —— 配额计数读视图。

设计要点：

1. **明文与 hash 严格分仓**：``ApiKeyRead`` / ``ApiKeyUsageRead`` 一
   律不含 ``plaintext_key``，确保 OpenAPI 在生成前端 client 时不会无
   意暴露明文字段。
2. **路径参数避免使用 hash**：bcrypt hash 含 ``$`` / ``/`` 等字符不
   适合做 URL path segment，因此 revoke / usage 全部走 POST + JSON
   body 形式（``ApiKeyHashRequest``），保持 URL 干净。
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """创建 API key 的请求体。

    所有字段都给了运营友好默认值（沿用
    :class:`app.models.api_quota.ApiKeyQuota` server_default），方便管
    理面板「直接创建」一键生成可用 key。
    """

    description: str = Field(
        "",
        max_length=255,
        description="key 用途备注，便于在管理面板辨认归属",
    )
    daily_limit: int = Field(
        1000,
        ge=0,
        description="日调用上限；0 表示禁用调用",
    )
    monthly_limit: int = Field(
        30000,
        ge=0,
        description="月调用上限；0 表示禁用调用",
    )
    rate_per_minute: int = Field(
        60,
        ge=0,
        description="每分钟请求数上限（限流参数，由后续中间件消费）",
    )


class ApiKeyHashRequest(BaseModel):
    """以 ``api_key_hash`` 为唯一键的 POST body。

    ``revoke`` / ``usage`` 接口共用，避免在 URL path 中携带 bcrypt
    hash（含 ``$``、``/`` 等不友好字符）。
    """

    api_key_hash: str = Field(
        ...,
        min_length=1,
        description="目标 key 的 bcrypt hash，由 create 响应一次性返回，可在 list 接口再次获取",
    )


class ApiKeyRead(BaseModel):
    """API key 读视图。

    用于 ``GET /api/v1/settings/api-keys`` 列表与详情，永远不含明文
    字段。``model_config`` 启用 ``from_attributes`` 让路由层可以
    ``ApiKeyRead.model_validate(orm_row)`` 一键序列化。
    """

    model_config = ConfigDict(from_attributes=True)

    api_key_hash: str = Field(..., description="bcrypt hash（兼作内部 ID）")
    description: str = Field(..., description="备注")
    daily_limit: int = Field(..., description="日调用上限")
    monthly_limit: int = Field(..., description="月调用上限")
    rate_per_minute: int = Field(..., description="每分钟请求上限")
    consumed_today: int = Field(..., description="今日已消耗")
    consumed_this_month: int = Field(..., description="本月已消耗")
    last_reset_daily: date = Field(..., description="上次日重置日期")
    last_reset_monthly: date = Field(..., description="上次月重置日期")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最近更新时间")


class ApiKeyCreated(BaseModel):
    """创建成功响应（含 *仅本次* 可见的明文）。

    SaaS 调用方拿到 ``plaintext_key`` 后必须自行妥善保管；服务端不存
    储明文，无法二次签发同一明文。
    """

    plaintext_key: str = Field(
        ...,
        description="API key 明文，**仅创建时本次返回**，后端不存储；丢失后只能创建新的 key",
    )
    api_key_hash: str = Field(..., description="bcrypt hash（兼作内部 ID）")
    description: str = Field(..., description="备注")
    daily_limit: int = Field(..., description="日调用上限")
    monthly_limit: int = Field(..., description="月调用上限")
    rate_per_minute: int = Field(..., description="每分钟请求上限")
    is_active: bool = Field(..., description="是否启用（创建时默认 true）")
    created_at: datetime = Field(..., description="创建时间")


class ApiKeyUsageRead(BaseModel):
    """配额计数读视图。

    与 :class:`ApiKeyRead` 共用主表字段，仅聚焦"用了多少 / 还能用多
    少"的运营关注面。前端管理面板可基于此渲染配额条 / 告警。
    """

    model_config = ConfigDict(from_attributes=True)

    api_key_hash: str = Field(..., description="bcrypt hash（兼作内部 ID）")
    description: str = Field(..., description="备注")
    daily_limit: int = Field(..., description="日调用上限")
    monthly_limit: int = Field(..., description="月调用上限")
    consumed_today: int = Field(..., description="今日已消耗")
    consumed_this_month: int = Field(..., description="本月已消耗")
    last_reset_daily: date = Field(..., description="上次日重置日期")
    last_reset_monthly: date = Field(..., description="上次月重置日期")
    is_active: bool = Field(..., description="是否启用")


__all__ = [
    "ApiKeyCreateRequest",
    "ApiKeyCreated",
    "ApiKeyHashRequest",
    "ApiKeyRead",
    "ApiKeyUsageRead",
]
