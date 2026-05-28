"""StoryOutcome 服务（W22-T1，P4 Wave A 1/6）。

职责（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：

  * 业务校验（``gmv >= 0``、``completion_rate ∈ [0, 1]``、``recorded_at
    ≤ now``）—— 即便 schema 已经做过基础校验，service 层在写库前再做
    一次兜底，防止上游绕过 pydantic（例如内部直调 service）。
  * SQLAlchemy CRUD（create / list / patch / delete）。
  * 错误统一以 ``HTTPException`` 抛出，由 FastAPI 转换成 ``ApiResponse``。

为什么单独拆 ``outcome_service.py`` 而不复用 story_variants：
    StoryVariant 写入是"剧本生成"语义，而 StoryOutcome 写入是"投放复盘"
    语义，两者生命周期、字段、校验规则差异巨大；保持独立 service 让
    后续扩展（例如批量导入、与平台 API 对接的自动同步）不必拆分共享类。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryOutcome, StoryVariant
from app.models.types import Platform
from app.schemas.commerce.outcome import StoryOutcomeCreate, StoryOutcomeUpdate
from app.services.common.errors import entity_not_found


def _enum_value(value: object) -> str:
    """把 ``Platform`` 枚举转为字符串值；接受 str 直接透传。"""
    if isinstance(value, Platform):
        return value.value
    return str(value)


class StoryOutcomeService:
    """story_outcomes 表的最小 CRUD 编排。"""

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步数据库会话；单次请求复用，由路由层 ``Depends(get_db)`` 注入。"""
        self._db = db

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_completion_rate(name: str, value: float | None) -> None:
        """``completion_rate_*`` 必须为空或位于 ``[0, 1]``。"""
        if value is None:
            return
        if value < 0 or value > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name} must be within [0, 1]",
            )

    @staticmethod
    def _validate_gmv(value: float) -> None:
        """``gmv`` 不允许负数（业务侧不存在负 GMV 投放结果）。"""
        if value < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gmv must be >= 0",
            )

    @staticmethod
    def _validate_recorded_at(value: datetime) -> None:
        """``recorded_at`` 不允许超过当前时间。

        允许 60 秒的客户端时钟漂移窗口，避免毫秒级时差导致合法回传被
        误判为未来值。naive datetime 一律视为 UTC，统一比较口径。
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if normalized > now + timedelta(seconds=60):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="recorded_at must not be in the future",
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, body: StoryOutcomeCreate) -> StoryOutcome:
        """创建一条 outcome 记录；写库前做业务校验。

        Args:
            body: 已通过 schema 层基础校验的创建请求。

        Returns:
            刷新后的 :class:`StoryOutcome` 实例（含 id / created_at /
            updated_at）。

        Raises:
            HTTPException: 400 当业务规则失败（gmv 负 / rate 越界 /
                recorded_at 越界）。
        """
        self._validate_completion_rate("completion_rate_3s", body.completion_rate_3s)
        self._validate_completion_rate("completion_rate_full", body.completion_rate_full)
        self._validate_gmv(body.gmv)
        self._validate_recorded_at(body.recorded_at)

        variant = await self._db.get(StoryVariant, body.variant_id)
        if variant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("StoryVariant"),
            )

        outcome = StoryOutcome(
            variant_id=body.variant_id,
            platform=_enum_value(body.platform),
            plays=body.plays,
            completion_rate_3s=body.completion_rate_3s,
            completion_rate_full=body.completion_rate_full,
            interactions=body.interactions,
            cart_clicks=body.cart_clicks,
            orders=body.orders,
            gmv=body.gmv,
            notes=body.notes,
            raw_payload=body.raw_payload or {},
            recorded_at=body.recorded_at,
        )
        self._db.add(outcome)
        await self._db.flush()
        await self._db.refresh(outcome)
        return outcome

    async def list_by_variant(self, variant_id: str) -> list[StoryOutcome]:
        """按 ``variant_id`` 列出投放效果记录，按 ``recorded_at desc`` 排序。

        Args:
            variant_id: 必填；未匹配时返回空列表。

        Returns:
            按记录时点倒序的 outcome 列表（最新在前）。
        """
        stmt = (
            select(StoryOutcome)
            .where(StoryOutcome.variant_id == variant_id)
            .order_by(StoryOutcome.recorded_at.desc(), StoryOutcome.id.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def _get_or_404(self, outcome_id: int) -> StoryOutcome:
        """按主键加载 outcome，缺失时返回 404，集中文案。"""
        obj = await self._db.get(StoryOutcome, outcome_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("StoryOutcome"),
            )
        return obj

    async def update(self, outcome_id: int, body: StoryOutcomeUpdate) -> StoryOutcome:
        """部分更新一条 outcome；仅显式传入的字段会被覆盖。

        关键内部逻辑：

        * 通过 ``model_dump(exclude_unset=True)`` 取出"用户主动传入"的字段
          集合，避免 None 误覆盖。
        * 业务校验（rate/gmv/recorded_at）只对显式覆盖的字段触发；未变更
          字段保持原值，无需重新验证。
        * ``platform`` 字段统一字符串化，避免存入 Enum 实例。

        Args:
            outcome_id: 待更新的记录主键。
            body: 部分更新请求；全部字段可选。

        Returns:
            更新并 refresh 后的 :class:`StoryOutcome` 实例。

        Raises:
            HTTPException: 404 当 outcome 不存在；400 当 PATCH 字段触发
                业务校验失败。
        """
        outcome = await self._get_or_404(outcome_id)
        patch = body.model_dump(exclude_unset=True)

        if "completion_rate_3s" in patch:
            self._validate_completion_rate("completion_rate_3s", patch["completion_rate_3s"])
        if "completion_rate_full" in patch:
            self._validate_completion_rate("completion_rate_full", patch["completion_rate_full"])
        if "gmv" in patch and patch["gmv"] is not None:
            self._validate_gmv(float(patch["gmv"]))
        if "recorded_at" in patch and patch["recorded_at"] is not None:
            self._validate_recorded_at(patch["recorded_at"])

        for field, value in patch.items():
            if field == "platform" and value is not None:
                setattr(outcome, field, _enum_value(value))
            else:
                setattr(outcome, field, value)

        await self._db.flush()
        await self._db.refresh(outcome)
        return outcome

    async def delete(self, outcome_id: int) -> None:
        """删除一条 outcome；幂等：缺失时返回 404 而非静默成功。"""
        outcome = await self._get_or_404(outcome_id)
        await self._db.delete(outcome)
        await self._db.flush()


__all__ = ["StoryOutcomeService"]
