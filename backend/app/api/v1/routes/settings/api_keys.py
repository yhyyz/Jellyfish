"""``/api/v1/settings/api-keys`` admin endpoints（P4 W24-T1）。

提供 API key 全生命周期的管理面板入口：

- ``POST /``：创建一条新 key，**plaintext 仅本次返回**；
- ``GET /``：列出所有 key（默认排除已 revoke 的 inactive 行）；
- ``POST /revoke``：以 hash 为键 soft-revoke；
- ``POST /usage``：以 hash 为键查询实时配额计数。

实现约定遵循 ``AGENTS.md`` 第 4 条：路由层只负责收参 / 鉴权 / 包装
``ApiResponse``，CRUD 业务逻辑下沉到
:mod:`app.services.api_quota.quota_service`；明文生成、bcrypt 哈希、
原子配额扣减均不在路由层落地。

为什么 ``revoke`` / ``usage`` 走 POST + JSON body 而不是
RESTful path/DELETE：

    bcrypt hash 含 ``$`` / ``/`` 等字符，作为 path segment 必须 URL
    编码，前端 generated client 体验糟糕；admin 面板调用频率极低，
    POST + body 更稳妥。这一点也写进了
    :class:`app.schemas.settings.api_key.ApiKeyHashRequest` 的 docstring。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.schemas.common import ApiResponse, created_response, success_response
from app.schemas.settings.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreated,
    ApiKeyHashRequest,
    ApiKeyRead,
    ApiKeyUsageRead,
)
from app.services.api_quota.quota_service import (
    create_api_key,
    get_usage,
    list_api_keys,
    revoke_api_key,
)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post(
    "",
    response_model=ApiResponse[ApiKeyCreated],
    status_code=201,
    summary="创建 API key（plaintext 仅本次返回）",
)
async def create_api_key_endpoint(
    payload: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ApiKeyCreated]:
    """创建一条新的 ``ApiKeyQuota`` 行。

    返回的 ``data.plaintext_key`` 是 SaaS 调用方今后唯一可见的明文，
    后端不存储——丢失后只能创建新的 key。
    """

    plaintext, row = await create_api_key(
        db,
        description=payload.description,
        daily_limit=payload.daily_limit,
        monthly_limit=payload.monthly_limit,
        rate_per_minute=payload.rate_per_minute,
    )
    data = ApiKeyCreated(
        plaintext_key=plaintext,
        api_key_hash=row.api_key_hash,
        description=row.description,
        daily_limit=row.daily_limit,
        monthly_limit=row.monthly_limit,
        rate_per_minute=row.rate_per_minute,
        is_active=row.is_active,
        created_at=row.created_at,
    )
    return created_response(data)


@router.get(
    "",
    response_model=ApiResponse[list[ApiKeyRead]],
    summary="列出 API key（默认排除已 revoke）",
)
async def list_api_keys_endpoint(
    include_inactive: bool = Query(
        False,
        description="是否包含已 revoke 的 inactive 行；缺省仅列活跃 key",
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ApiKeyRead]]:
    """列出所有 API key。

    路由层保持瘦身：直接 ``model_validate`` 委托给
    :class:`ApiKeyRead`，永不返回明文字段。
    """

    rows = await list_api_keys(db, include_inactive=include_inactive)
    return success_response([ApiKeyRead.model_validate(row) for row in rows])


@router.post(
    "/revoke",
    response_model=ApiResponse[ApiKeyRead],
    summary="Revoke API key（软删，保留历史计数）",
)
async def revoke_api_key_endpoint(
    payload: ApiKeyHashRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ApiKeyRead]:
    """将指定 key 标记为 ``is_active=False``。

    若 hash 不存在返回 404；重复 revoke 同一 key 幂等成功。
    """

    row = await revoke_api_key(db, api_key_hash=payload.api_key_hash)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"API key not found: {payload.api_key_hash}",
        )
    return success_response(ApiKeyRead.model_validate(row))


@router.post(
    "/usage",
    response_model=ApiResponse[ApiKeyUsageRead],
    summary="查询单条 API key 的配额计数",
)
async def get_api_key_usage_endpoint(
    payload: ApiKeyHashRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ApiKeyUsageRead]:
    """返回单条 key 的实时 ``consumed_today`` / ``consumed_this_month``。

    允许查询已 revoke 的 key（用于事后审计）；前端管理面板根据
    ``is_active`` 决定是否给出告警。
    """

    row = await get_usage(db, api_key_hash=payload.api_key_hash)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"API key not found: {payload.api_key_hash}",
        )
    return success_response(ApiKeyUsageRead.model_validate(row))


__all__ = ["router"]
