"""``ComplianceProfile`` / ``ComplianceFinding`` 只读查询服务（W6-T3）。

本服务承担 ``GET /api/v1/studio/compliance/*`` 三个读接口的业务逻辑：

- ``list_profiles``：列出系统级 + 业务自建的合规规则集，可按 ``region`` 过滤；
- ``get_profile``：按 ID 取出某个规则集的完整 ``rules`` JSON；
- ``list_findings``：按变体 ID 列出已记录的合规问题，可按严重度 / 解决态过滤。

为什么放在 ``services/commerce``：
    合规规则集与合规 finding 的“消费方”始终是剧情带货链路（脚本生成、
    发布前校验），不属于通用 studio 资产；从 service 分层视角属于 commerce。
    HTTP 路由侧暴露在 ``/studio/compliance``，是因为前端面板把它放在
    studio 工作台一侧（生产工序入口），但这只是 UI 入口归属，与 service
    职责归属不冲突——这里维持“路由位置 ≠ 业务归属”的既有约定。

为什么 read schema 不在本模块构造：
    本服务只返回 dict（与 ``ApiResponse[dict]`` 结合），让上层 route 用
    ``ComplianceProfileRead.model_validate(...)`` 做最终序列化。这样下游
    如果要在 read schema 上加字段（比如展示规则计数），不需要改 service。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import ComplianceFinding, ComplianceProfile


def _profile_to_dict(row: ComplianceProfile) -> dict[str, Any]:
    """把一行 :class:`ComplianceProfile` 转成可被 read schema 验证的 dict。

    存在原因：
        ORM 行的 ``region`` 字段是字符串枚举（``ComplianceRegion``），直接
        塞进 read schema 的 ``str`` 字段需要一次 ``str(...)`` 归一化；同样
        ``rules`` 列存 JSON，可能是 ``None`` 或 ``[]``，前端期望永远是 list。
    """

    region_value = row.region.value if hasattr(row.region, "value") else str(row.region)
    return {
        "id": row.id,
        "name": row.name,
        "region": region_value,
        "rules": list(row.rules or []),
        "is_system": bool(row.is_system),
        "description": row.description or "",
        "created_at": row.created_at,
    }


def _finding_to_dict(row: ComplianceFinding) -> dict[str, Any]:
    """把一行 :class:`ComplianceFinding` 转成可被 read schema 验证的 dict。"""

    severity_value = (
        row.severity.value if hasattr(row.severity, "value") else str(row.severity)
    )
    return {
        "id": row.id,
        "variant_id": row.variant_id,
        "severity": severity_value,
        "rule_id": row.rule_id,
        "rule_kind": row.rule_kind,
        "description": row.description,
        "location": row.location,
        "suggested_fix": row.suggested_fix,
        "is_resolved": bool(row.is_resolved),
        "detected_at": row.detected_at,
    }


class ComplianceQueryService:
    """合规规则集/finding 的只读查询 service。

    Args:
        db: 当前 HTTP 请求绑定的 :class:`AsyncSession`。本服务不会写库，
            也不会主动 commit，纯读路径。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # ComplianceProfile 查询
    # ------------------------------------------------------------------

    async def list_profiles(
        self,
        *,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出合规规则集，按 ``region`` 可选过滤。

        Args:
            region: 适用地域字符串（``cn_mainland`` / ``hk_tw`` / ``overseas``）；
                None 表示不过滤。

        Returns:
            按 ``id`` 升序的规则集 dict 列表，可被 :class:`ComplianceProfileRead`
            ``model_validate`` 直接消费。
        """

        stmt = select(ComplianceProfile).order_by(ComplianceProfile.id.asc())
        if region:
            stmt = stmt.where(ComplianceProfile.region == region)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [_profile_to_dict(r) for r in rows]

    async def get_profile(self, profile_id: str) -> dict[str, Any]:
        """按 ID 取一个合规规则集的完整快照。

        Args:
            profile_id: profile 主键，如 ``cn_mainland_default``。

        Raises:
            HTTPException: 404 当 ``profile_id`` 不存在。

        Returns:
            可被 :class:`ComplianceProfileRead` 消费的 dict。
        """

        row = await self.db.get(ComplianceProfile, profile_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"compliance profile not found: {profile_id}",
            )
        return _profile_to_dict(row)

    # ------------------------------------------------------------------
    # ComplianceFinding 查询
    # ------------------------------------------------------------------

    async def list_findings(
        self,
        *,
        variant_id: str,
        severity: str | None = None,
        is_resolved: bool | None = None,
    ) -> list[dict[str, Any]]:
        """按变体列出合规 finding，可按严重度/解决态过滤。

        Args:
            variant_id: 变体 ID；必填，因为 finding 永远依附在变体上。
            severity: ``info`` / ``warning`` / ``blocker`` 之一；None 表示不过滤。
            is_resolved: True 只看已解决；False 只看未解决；None 不过滤。

        Returns:
            按 ``id`` 升序的 finding dict 列表（同一变体下行数有限，无需分页）。
        """

        stmt = (
            select(ComplianceFinding)
            .where(ComplianceFinding.variant_id == variant_id)
            .order_by(ComplianceFinding.id.asc())
        )
        if severity:
            stmt = stmt.where(ComplianceFinding.severity == severity)
        if is_resolved is not None:
            stmt = stmt.where(ComplianceFinding.is_resolved == is_resolved)

        rows = (await self.db.execute(stmt)).scalars().all()
        return [_finding_to_dict(r) for r in rows]


__all__ = [
    "ComplianceQueryService",
]
