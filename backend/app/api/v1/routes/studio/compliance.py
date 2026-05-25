"""``/api/v1/studio/compliance/*`` 只读路由（W6-T3）。

3 个 GET 端点：

- ``GET /studio/compliance/profiles``：列出合规规则集，可按 ``region`` 过滤。
- ``GET /studio/compliance/profiles/{profile_id}``：取单个规则集详情。
- ``GET /studio/compliance/findings?variant_id=X``：列出某个变体的合规问题，
  可按 ``severity`` / ``is_resolved`` 过滤。

路由层只做收参 + 调 :class:`ComplianceQueryService` + 包统一响应壳。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.compliance import (
    ComplianceFindingRead,
    ComplianceProfileRead,
)
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.compliance_query import ComplianceQueryService

router = APIRouter()


@router.get(
    "/profiles",
    response_model=ApiResponse[list[ComplianceProfileRead]],
    summary="列出合规规则集（可按 region 过滤）",
)
async def list_compliance_profiles(
    region: str | None = Query(None, description="过滤地域：cn_mainland / hk_tw / overseas"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ComplianceProfileRead]]:
    """列出合规规则集。"""

    service = ComplianceQueryService(db)
    rows = await service.list_profiles(region=region)
    items = [ComplianceProfileRead.model_validate(r) for r in rows]
    return success_response(items)


@router.get(
    "/profiles/{profile_id}",
    response_model=ApiResponse[ComplianceProfileRead],
    summary="取单个合规规则集详情",
)
async def get_compliance_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ComplianceProfileRead]:
    """取单个合规规则集详情，未命中返回 404。"""

    service = ComplianceQueryService(db)
    payload = await service.get_profile(profile_id)
    return success_response(ComplianceProfileRead.model_validate(payload))


@router.get(
    "/findings",
    response_model=ApiResponse[list[ComplianceFindingRead]],
    summary="列出某变体的合规 finding（可按严重度/解决态过滤）",
)
async def list_compliance_findings(
    variant_id: str = Query(..., description="所属变体 ID（必填）"),
    severity: str | None = Query(None, description="过滤严重度：info / warning / blocker"),
    is_resolved: bool | None = Query(None, description="过滤解决态：true 已解决 / false 未解决"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ComplianceFindingRead]]:
    """列出某变体的合规 finding。"""

    service = ComplianceQueryService(db)
    rows = await service.list_findings(
        variant_id=variant_id,
        severity=severity,
        is_resolved=is_resolved,
    )
    items = [ComplianceFindingRead.model_validate(r) for r in rows]
    return success_response(items)
