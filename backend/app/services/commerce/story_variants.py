"""StoryVariant 服务（W6-T2 + W14-T3，P1/A-B 阶段）。

P1 仅承担 **手动创建** 与 **列表读取** 两类入口：

- :meth:`StoryVariantsService.create` 接收前端整理好的剧本与镜头分解
  JSON，落库一条 ``status=draft`` 的变体记录；自动化生成（LLM 生成
  剧本 + 自动落库）属于 W6-T3 范畴，此处刻意保持手动入口。
- :meth:`StoryVariantsService.list_variants` 强制按 ``project_id``
  过滤，可选按 ``chapter_id`` / ``status`` 进一步收敛；按 ``created_at
  desc`` 给前端"最新优先"的列表语义。

W14-T3 在此基础上扩展 A/B 变体管理：

- :meth:`StoryVariantsService.clone_variant` 基于已有变体派生一个新的
  ``draft`` 变体，可选覆盖 ``archetype`` / ``hook_pattern_id`` /
  ``cta_pattern_id`` / ``formula_id``，剧本与镜头分解深拷贝，新 ID 由
  服务端生成。
- :meth:`StoryVariantsService.mark_champion` 在 ``(project_id,
  chapter_id)`` 命名空间内单选冠军：标记目标变体的同时清空同章节其它
  变体的 ``is_champion``，保证同一章节同时只有 1 个冠军。

冠军变体（``is_champion``）与合规评分（``compliance_score``）在 P1 不
开放写入：
- ``is_champion`` 由 W14-T3 ``PATCH .../champion`` 单独路径推进。
- ``compliance_score`` 由合规检查 worker 写入，避免客户端绕过检查。
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status as http_status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryVariant
from app.models.types import StoryVariantStatus
from app.schemas.commerce.story_variant import (
    StoryVariantCloneRequest,
    StoryVariantCreate,
    StoryVariantRead,
)
from app.services.common.errors import entity_not_found


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

    async def _get_or_404(self, variant_id: str) -> StoryVariant:
        """按 ID 加载变体，缺失时统一抛 404，集中错误文案。"""
        obj = await self._db.get(StoryVariant, variant_id)
        if obj is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("StoryVariant"),
            )
        return obj

    async def clone_variant(
        self,
        variant_id: str,
        body: StoryVariantCloneRequest,
    ) -> dict[str, Any]:
        """克隆现有变体，可选覆盖 archetype/hook/cta/formula 字段。

        语义约束（W14-T3）：

        * 新 ``id`` 由服务端 ``uuid4().hex`` 生成；客户端无法指定。
        * ``script_full_text`` 与 ``script_breakdown`` 从源变体 **深拷贝**，
          避免修改新变体时反向影响源 JSON。
        * ``status`` 强制重置为 ``draft``，``is_champion`` 重置为 ``False``，
          ``compliance_score`` 重置为 ``0``——保持"派生即新草稿"的语义，
          A/B 流程必须重新走完合规检查与冠军评估。
        * ``project_id`` / ``chapter_id`` / ``generated_by_task_id`` 沿用
          源变体；A/B 派生默认在同一章节内做对照实验。
        * 覆盖字段为 ``None`` 时表示"保持源值"，仅显式传入的字段会被改写。

        Args:
            variant_id: 源变体 ID。
            body: 克隆请求（可选覆盖项）。

        Returns:
            序列化后的新变体字典（与 ``StoryVariantRead`` 一致）。

        Raises:
            HTTPException: 当 ``variant_id`` 不存在时返回 404。
        """
        source = await self._get_or_404(variant_id)
        cloned = StoryVariant(
            id=uuid4().hex,
            project_id=source.project_id,
            chapter_id=source.chapter_id,
            formula_id=body.new_formula_id or source.formula_id,
            hook_pattern_id=body.new_hook_pattern_id or source.hook_pattern_id,
            cta_pattern_id=body.new_cta_pattern_id or source.cta_pattern_id,
            archetype=body.new_archetype or source.archetype,
            script_full_text=source.script_full_text,
            script_breakdown=copy.deepcopy(source.script_breakdown or {}),
            status=StoryVariantStatus.draft.value,
            is_champion=False,
            compliance_score=0,
            generated_by_task_id=source.generated_by_task_id,
        )
        self._db.add(cloned)
        await self._db.flush()
        await self._db.refresh(cloned)
        return StoryVariantRead.model_validate(cloned).model_dump(mode="json")

    async def mark_champion(self, variant_id: str) -> dict[str, Any]:
        """标记此变体为 champion，并取消同章节其它变体的 champion 标记。

        语义约束（W14-T3）：

        * 唯一性命名空间为 ``(project_id, chapter_id)``：同一章节同时只
          能有 1 个冠军；其它章节 / 其它项目下的冠军不受影响。
        * 实现策略采用 **批量 UPDATE + 单点 SET**：先把同章节其它变体
          ``is_champion`` 清零，再把目标变体标记为 ``True``，避免 N+1
          查询；两步在同一事务内完成由调用方（``get_db``）保证原子性。
        * 幂等：对已经是冠军的变体再次调用同样得到 ``is_champion=True``，
          不会因主键冲突或重复 UPDATE 产生副作用。

        Args:
            variant_id: 目标变体 ID。

        Returns:
            序列化后的目标变体字典（``is_champion=True``）。

        Raises:
            HTTPException: 当 ``variant_id`` 不存在时返回 404。
        """
        target = await self._get_or_404(variant_id)
        await self._db.execute(
            update(StoryVariant)
            .where(
                StoryVariant.project_id == target.project_id,
                StoryVariant.chapter_id == target.chapter_id,
                StoryVariant.id != target.id,
                StoryVariant.is_champion.is_(True),
            )
            .values(is_champion=False)
        )
        target.is_champion = True
        await self._db.flush()
        await self._db.refresh(target)
        return StoryVariantRead.model_validate(target).model_dump(mode="json")


__all__ = [
    "StoryVariantsService",
]
