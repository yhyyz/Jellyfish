"""StoryVariant 服务（W6-T2，P1 阶段）。

P1 仅承担 **手动创建** 与 **列表读取** 两类入口：

- :meth:`StoryVariantsService.create` 接收前端整理好的剧本与镜头分解
  JSON，落库一条 ``status=draft`` 的变体记录；自动化生成（LLM 生成
  剧本 + 自动落库）属于 W6-T3 范畴，此处刻意保持手动入口。
- :meth:`StoryVariantsService.list_variants` 强制按 ``project_id``
  过滤，可选按 ``chapter_id`` / ``status`` 进一步收敛；按 ``created_at
  desc`` 给前端"最新优先"的列表语义。

冠军变体（``is_champion``）与合规评分（``compliance_score``）在 P1 不
开放写入：
- ``is_champion`` 由 P2 ``PATCH .../champion`` 单独路径推进。
- ``compliance_score`` 由合规检查 worker 写入，避免客户端绕过检查。
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryVariant
from app.models.types import StoryVariantStatus
from app.schemas.commerce.story_variant import StoryVariantCreate


class StoryVariantsService:
    """变体表读写编排（仅 P1 范围内的入口）。"""

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步数据库会话。"""
        self._db = db

    async def create(self, body: StoryVariantCreate) -> StoryVariant:
        """手动创建一个 ``draft`` 状态的变体。

        服务端固定的字段（避免客户端绕过）：
        - ``id``：``uuid4().hex`` 自动生成；
        - ``status``：固定 ``draft``，自动化生成完成后才能转 ``ready``；
        - ``is_champion``：固定 ``False``，P2 才允许标记冠军；
        - ``compliance_score``：固定 ``0``，由合规检查 worker 后续覆盖。

        Args:
            body: 业务字段（project_id / chapter_id / formula_id /
                script_full_text / script_breakdown / archetype /
                generated_by_task_id）。

        Returns:
            刷新后的 :class:`StoryVariant` 实例（含 ``created_at`` /
            ``updated_at``）。
        """
        variant = StoryVariant(
            id=uuid4().hex,
            project_id=body.project_id,
            chapter_id=body.chapter_id,
            formula_id=body.formula_id,
            archetype=body.archetype,
            script_full_text=body.script_full_text,
            script_breakdown=body.script_breakdown or {},
            status=StoryVariantStatus.draft.value,
            is_champion=False,
            compliance_score=0,
            generated_by_task_id=body.generated_by_task_id,
        )
        self._db.add(variant)
        await self._db.flush()
        await self._db.refresh(variant)
        return variant

    async def list_variants(
        self,
        *,
        project_id: str,
        chapter_id: str | None = None,
        status: StoryVariantStatus | None = None,
    ) -> list[StoryVariant]:
        """按 ``project_id`` 过滤变体列表，按 ``created_at desc`` 排序。

        Args:
            project_id: 必填，限制在指定项目内。
            chapter_id: 可选，按章节进一步过滤。
            status: 可选，按变体状态过滤。

        Returns:
            按创建时间倒序的变体列表（空列表也是合法返回）。
        """
        stmt = select(StoryVariant).where(StoryVariant.project_id == project_id)
        if chapter_id is not None:
            stmt = stmt.where(StoryVariant.chapter_id == chapter_id)
        if status is not None:
            stmt = stmt.where(StoryVariant.status == status.value)
        stmt = stmt.order_by(StoryVariant.created_at.desc(), StoryVariant.id.asc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "StoryVariantsService",
]
