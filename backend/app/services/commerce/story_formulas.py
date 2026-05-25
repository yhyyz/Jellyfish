"""StoryFormula 只读 service（W6-T2，P1 阶段）。

剧情公式注册表为系统级种子数据，不允许 API 层进行创建/编辑/删除：
- 写入路径在 :func:`app.services.commerce.builtin_story_formulas.bootstrap_builtin_story_formulas`
  统一管理（启动期幂等加载 6 条内置公式）。
- 应用层只通过本 service 暴露列表 / 详情 read 入口，避免运营误操作。

本模块刻意不复用 ``app.services.studio`` 下的通用 CRUD 模式：
通用 CRUD 提供 create/update/delete 能力，会模糊只读约束；这里直接
组装查询并返回纯 ORM 对象，由路由层负责 schema 序列化。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryFormula
from app.models.types import FormulaRegion
from app.services.common.errors import entity_not_found


class StoryFormulasService:
    """只读访问 ``story_formulas`` 注册表。

    使用注入式 ``AsyncSession``，与项目其它 service 的实例化风格保持一致；
    不缓存数据，每次查询都打到 DB（公式表数量极小，规模在 10 条以内）。
    """

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步数据库会话。"""
        self._db = db

    async def list_formulas(
        self,
        *,
        region: FormulaRegion | None = None,
        category: str | None = None,
    ) -> list[StoryFormula]:
        """返回公式列表（默认按 ``sort_order`` 升序）。

        Args:
            region: 仅返回指定地域的公式（cn / global）；为空时不过滤。
            category: 按 ``category`` 字段精确匹配；为空时不过滤。

        Returns:
            按 ``sort_order`` 升序的 :class:`StoryFormula` 列表。
        """
        stmt = select(StoryFormula)
        if region is not None:
            stmt = stmt.where(StoryFormula.region == region.value)
        if category is not None:
            stmt = stmt.where(StoryFormula.category == category)
        stmt = stmt.order_by(StoryFormula.sort_order.asc(), StoryFormula.id.asc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_formula(self, formula_id: str) -> StoryFormula:
        """根据 ID 获取公式，不存在时抛出 404。

        Args:
            formula_id: 公式 ID（如 ``underdog_triumph``）。

        Raises:
            HTTPException: 当 ID 不匹配任何系统公式时返回 404。
        """
        obj = await self._db.get(StoryFormula, formula_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("StoryFormula"),
            )
        return obj


__all__ = [
    "StoryFormulasService",
]
