"""Pattern library 只读 service（W14-T4，P2 钩子/CTA/原型选择器）。

本 service 聚合 P2 钩子工作流（Wave 13/14）下三类系统级注册表的只读
访问入口：

- 钩子模式（``hook_patterns`` 表，10 条内置）
- CTA 模式（``cta_patterns`` 表，5 条内置）
- 品牌人格原型（``brand_archetypes`` 表，12 条内置）

三张表均是系统级种子数据（``is_system=True``），写入路径只在启动期由对
应 ``bootstrap_builtin_*`` 函数管理，应用层只暴露列表/详情两类只读
接口，避免运营误改。

设计思路：
- 复用 :class:`app.services.commerce.story_formulas.StoryFormulasService`
  的"实例化 + 注入 ``AsyncSession``"风格，三类查询共享同一个 session。
- 返回 ``list[dict]`` / ``dict``：方便路由层直接走
  :class:`pydantic.BaseModel.model_validate` 包裹成 ApiResponse；ORM 行
  与 schema 字段大体一一对应，但 ``voice_traits`` 在 ORM 中是 ``list``
  而 schema 暴露为 ``dict[str, Any]``，本 service 集中做这一层转换。
- 默认按 ``sort_order ASC`` 排序，再以 ``id ASC`` 兜底，保证同 sort_order
  的输出顺序稳定（与 :class:`StoryFormulasService` 同款约定）。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_archetype import BrandArchetype
from app.models.cta_pattern import CtaPattern
from app.models.hook_pattern import HookPattern
from app.services.common.errors import entity_not_found


def _hook_to_dict(obj: HookPattern) -> dict[str, Any]:
    """把 :class:`HookPattern` ORM 行展开为 schema-friendly dict。

    单独抽函数便于 list/get 路径共享同一份字段映射，避免重复维护。
    """
    return {
        "id": obj.id,
        "name": obj.name,
        "pattern_type": obj.pattern_type,
        "description": obj.description,
        "template_text": obj.template_text,
        "psychology": obj.psychology,
        "use_cases": list(obj.use_cases or []),
        "avoid_cases": list(obj.avoid_cases or []),
        "is_system": obj.is_system,
        "sort_order": obj.sort_order,
        "created_at": obj.created_at,
    }


def _cta_to_dict(obj: CtaPattern) -> dict[str, Any]:
    """把 :class:`CtaPattern` ORM 行展开为 schema-friendly dict。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "hardness": obj.hardness,
        "urgency_type": obj.urgency_type,
        "description": obj.description,
        "template_text": obj.template_text,
        "sample_phrases": list(obj.sample_phrases or []),
        "is_system": obj.is_system,
        "sort_order": obj.sort_order,
        "created_at": obj.created_at,
    }


def _archetype_to_dict(obj: BrandArchetype) -> dict[str, Any]:
    """把 :class:`BrandArchetype` ORM 行展开为 schema-friendly dict。

    ``voice_traits`` 在 ORM 中以 ``list[str]`` 存储，schema 期望 ``dict``，
    这里包成 ``{"items": [...]}`` 便于前端做扩展（未来若新增 weight /
    intensity 等字段，无需破坏现有契约）。
    """
    voice_traits_raw = obj.voice_traits or []
    voice_traits_payload: dict[str, Any]
    if isinstance(voice_traits_raw, dict):
        voice_traits_payload = dict(voice_traits_raw)
    else:
        voice_traits_payload = {"items": list(voice_traits_raw)}

    speech_patterns_raw = obj.speech_patterns or {}
    speech_patterns_payload: dict[str, Any]
    if isinstance(speech_patterns_raw, dict):
        speech_patterns_payload = dict(speech_patterns_raw)
    else:
        speech_patterns_payload = {"items": list(speech_patterns_raw)}

    return {
        "id": obj.id,
        "name": obj.name,
        "name_zh": obj.name_zh,
        "motivation": obj.motivation,
        "voice_traits": voice_traits_payload,
        "speech_patterns": speech_patterns_payload,
        "sample_brands": list(obj.sample_brands or []),
        "is_system": obj.is_system,
        "sort_order": obj.sort_order,
        "created_at": obj.created_at,
    }


class PatternLibraryService:
    """只读访问 ``hook_patterns`` / ``cta_patterns`` / ``brand_archetypes``。

    实例化时注入 ``AsyncSession``，三类查询共享同一个会话。所有 list 方
    法默认按 ``sort_order`` 升序输出；所有 get 方法在记录不存在时抛出
    HTTP 404。

    本 service 故意不引入跨表 join 或缓存：注册表规模都很小（10/5/12
    条），每次请求直接打 DB 也没有性能问题，避免引入额外失效路径。
    """

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步数据库会话。"""
        self._db = db

    # ------------------------------------------------------------------
    # HookPattern
    # ------------------------------------------------------------------

    async def list_hook_patterns(
        self,
        *,
        pattern_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出所有钩子模式（默认按 ``sort_order`` 升序）。

        Args:
            pattern_type: 仅返回指定类型（``question`` / ``conflict`` /
                ``contrast`` / ``numerical`` / ``curiosity`` / ``shock``
                / ``relatable`` / ``dialogue`` / ``visual`` / ``pov``）；
                为空时不过滤。

        Returns:
            按 ``sort_order`` 升序的 dict 列表，每项字段与
            :class:`app.schemas.commerce.patterns.HookPatternRead` 对齐。
        """
        stmt = select(HookPattern)
        if pattern_type is not None:
            stmt = stmt.where(HookPattern.pattern_type == pattern_type)
        stmt = stmt.order_by(HookPattern.sort_order.asc(), HookPattern.id.asc())
        result = await self._db.execute(stmt)
        return [_hook_to_dict(item) for item in result.scalars().all()]

    async def get_hook_pattern(self, pattern_id: str) -> dict[str, Any]:
        """根据 ID 获取钩子模式，不存在时抛出 404。

        Args:
            pattern_id: 钩子 ID（如 ``question_hook``）。

        Raises:
            HTTPException: ID 不匹配任何系统钩子时返回 404。
        """
        obj = await self._db.get(HookPattern, pattern_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("HookPattern"),
            )
        return _hook_to_dict(obj)

    # ------------------------------------------------------------------
    # CtaPattern
    # ------------------------------------------------------------------

    async def list_cta_patterns(
        self,
        *,
        hardness: str | None = None,
        urgency_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出所有 CTA 模式（默认按 ``sort_order`` 升序）。

        Args:
            hardness: 仅返回指定硬度（``soft`` / ``medium`` / ``hard``）；
                为空时不过滤。
            urgency_type: 仅返回指定驱动类型（``scarcity`` / ``urgency``
                / ``social_proof`` / ``benefit`` / ``risk_removal``）；
                为空时不过滤。

        Returns:
            按 ``sort_order`` 升序的 dict 列表。两个过滤参数同时给出时取
            交集（AND 关系）。
        """
        stmt = select(CtaPattern)
        if hardness is not None:
            stmt = stmt.where(CtaPattern.hardness == hardness)
        if urgency_type is not None:
            stmt = stmt.where(CtaPattern.urgency_type == urgency_type)
        stmt = stmt.order_by(CtaPattern.sort_order.asc(), CtaPattern.id.asc())
        result = await self._db.execute(stmt)
        return [_cta_to_dict(item) for item in result.scalars().all()]

    async def get_cta_pattern(self, pattern_id: str) -> dict[str, Any]:
        """根据 ID 获取 CTA 模式，不存在时抛出 404。

        Args:
            pattern_id: CTA ID（如 ``scarcity_cta``）。

        Raises:
            HTTPException: ID 不匹配任何系统 CTA 时返回 404。
        """
        obj = await self._db.get(CtaPattern, pattern_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("CtaPattern"),
            )
        return _cta_to_dict(obj)

    # ------------------------------------------------------------------
    # BrandArchetype
    # ------------------------------------------------------------------

    async def list_brand_archetypes(self) -> list[dict[str, Any]]:
        """列出所有品牌人格原型（默认按 ``sort_order`` 升序）。

        Returns:
            按 ``sort_order`` 升序的 dict 列表，与
            :class:`app.schemas.commerce.patterns.BrandArchetypeRead` 对齐。
        """
        stmt = (
            select(BrandArchetype)
            .order_by(BrandArchetype.sort_order.asc(), BrandArchetype.id.asc())
        )
        result = await self._db.execute(stmt)
        return [_archetype_to_dict(item) for item in result.scalars().all()]

    async def get_brand_archetype(self, archetype_id: str) -> dict[str, Any]:
        """根据 ID 获取品牌人格原型，不存在时抛出 404。

        Args:
            archetype_id: 原型 ID（如 ``sage`` / ``jester``）。

        Raises:
            HTTPException: ID 不匹配任何系统原型时返回 404。
        """
        obj = await self._db.get(BrandArchetype, archetype_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("BrandArchetype"),
            )
        return _archetype_to_dict(obj)


__all__ = [
    "PatternLibraryService",
]
