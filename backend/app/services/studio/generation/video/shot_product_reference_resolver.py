"""ShotProductReferenceResolver — 按 ``product_focus_level`` 优先级序列从挂载商品取参考图（W16 T16-5）。

为什么有这个模块：
- multi_ref 视频模型（如 happyhorse-1.0-r2v）需要将"商品在镜头中如何登场"
  转化成具体的 ProductImage 列表。
- ``shot.product_focus_level`` 描述了商品视觉聚焦级别（subtle/functional/hero/none），
  Decision H 为每个级别定义了 ``view_angle`` 优先级序列，本模块负责把镜头
  关联到的商品按该序列拉取 ``ProductImage.file_id`` 列表。
- ``ProjectProductLink`` 支持 project / chapter / shot 三种粒度，本模块按
  "最特定优先"原则取一档非空集合，保证镜头级覆盖能屏蔽全局兜底关联。
- 总结果再交给 ``ReferenceImageBudget`` 做 9 槽预算裁剪，保证不会超过模型上限。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commerce_assets import ProductImage, ProjectProductLink
from app.models.studio_projects import Chapter
from app.models.studio_shots import Shot
from app.models.types import AssetViewAngle, ProductFocusLevel
from app.services.studio.image_task_references import pick_ordered_ref_file_ids
from app.services.studio.reference_image_budget import (
    ReferenceImageBudget,
    ReferenceImageBudgetSpec,
)

# Decision H：每个 product_focus_level 对应的 view_angle 优先级序列。
# 注意顺序即优先级，前者优先放进最终列表；none 没有商品出现，返回空。
PRIORITY_BY_FOCUS_LEVEL: dict[ProductFocusLevel, tuple[AssetViewAngle, ...]] = {
    ProductFocusLevel.hero: (
        AssetViewAngle.front,
        AssetViewAngle.three_quarter,
        AssetViewAngle.detail,
    ),
    ProductFocusLevel.functional: (
        AssetViewAngle.detail,
        AssetViewAngle.three_quarter,
        AssetViewAngle.front,
    ),
    ProductFocusLevel.subtle: (
        AssetViewAngle.three_quarter,
        AssetViewAngle.front,
    ),
    ProductFocusLevel.none: (),
}


class ShotProductReferenceResolver:
    """按 ``product_focus_level`` 选择 ProductImage 参考图列表。

    流程（Decision H 优先级序列 + Decision G 9 槽预算）：

    1. 加载 Shot，得到 ``chapter_id`` 与 ``product_focus_level``；
       focus_level=none 直接返回空列表（走 t2v 而非 r2v）。
    2. 加载 Chapter，得到 ``project_id``。
    3. 按 ``shot_id`` > ``chapter_id`` > 仅 ``project_id`` 三档精度依次查
       ``ProjectProductLink``，取第一个非空集合作为最终挂载商品集合
       （最特定胜出，不跨档合并）。
    4. 对每个挂载 product 调用 ``pick_ordered_ref_file_ids``，按对应
       view_angle 序列收集 ``ProductImage.file_id``。
    5. 把按商品顺序拼接的 file_id 列表交给 ``ReferenceImageBudget``，
       用 ``max_total_override = max_total`` 收紧到模型可接受的总数（默认 9）。
    6. 返回 ``(file_ids, warnings)``，warnings 用于上游写任务元数据
       （比如"被预算裁掉了 N 张"或"该镜头未关联商品"等场景）。

    本类无状态，可在 build_run_args 层每次构造，无副作用。
    """

    def __init__(
        self,
        budget_spec: ReferenceImageBudgetSpec | None = None,
    ) -> None:
        """构造解析器。

        Args:
            budget_spec: 自定义参考图预算配额。None 时使用默认 5/3/2/9 配置；
                传入 ``ReferenceImageBudgetSpec`` 可覆盖单次解析时的槽位上限。
        """
        self._budget_spec: ReferenceImageBudgetSpec | None = budget_spec

    async def resolve(
        self,
        db: AsyncSession,
        *,
        shot_id: str,
        max_total: int = 9,
        focus_level_override: ProductFocusLevel | None = None,
    ) -> tuple[list[str], list[str]]:
        """解析镜头的商品参考图列表。

        Args:
            db: 异步 SQLAlchemy 会话。
            shot_id: 目标镜头 ID。
            max_total: 总参考图上限（受模型 ``max_reference_images`` 约束，默认 9）。
            focus_level_override: 显式指定 focus_level（用于"DB=none 但临时按 hero
                走预览"等调试场景）；为 None 时取 ``shot.product_focus_level``。

        Returns:
            ``(file_ids, warnings)``：
            - ``file_ids``：按 Decision H 优先级序列与商品顺序拼接、并经过
              ``ReferenceImageBudget`` 裁剪后的 ``ProductImage.file_id`` 列表。
            - ``warnings``：解释性告警，可写入任务元数据（如 focus_level=none
              直接跳过、未关联商品、商品无可用图、预算溢出等）。
        """
        warnings: list[str] = []

        # 1. 加载 Shot 与有效 focus_level。
        shot = await db.get(Shot, shot_id)
        if shot is None:
            return [], [f"shot not found: {shot_id}"]
        focus_level = focus_level_override or shot.product_focus_level

        # 2. focus_level=none 直接退出（应走 t2v 而不是 multi_ref）。
        if focus_level == ProductFocusLevel.none:
            return [], [
                "product_focus_level is none; no product references resolved",
            ]
        view_angles = PRIORITY_BY_FOCUS_LEVEL[focus_level]

        # 3. 加载 Chapter，得到 project_id。
        chapter = await db.get(Chapter, shot.chapter_id)
        if chapter is None:
            return [], [f"chapter not found for shot: {shot_id}"]

        # 4. 按 shot > chapter > project 三档精度查 ProjectProductLink，取最特定档。
        product_ids = await self._resolve_linked_product_ids(
            db,
            project_id=chapter.project_id,
            chapter_id=shot.chapter_id,
            shot_id=shot_id,
        )
        if not product_ids:
            return [], ["镜头未关联任何商品"]

        # 5. 对每个 product 按 view_angle 优先级序列拉取 file_id。
        collected: list[str] = []
        for product_id in product_ids:
            file_ids = await pick_ordered_ref_file_ids(
                db,
                image_model=ProductImage,
                parent_field_name="product_id",
                parent_id=product_id,
                view_angles=view_angles,
            )
            collected.extend(file_ids)

        if not collected:
            return [], [
                "已关联商品但未找到任何符合优先级序列的 ProductImage",
            ]

        # 6. 用 ReferenceImageBudget 裁剪到 max_total（默认 9）。
        # multi_ref 仅取商品图（无 character/scene），因此默认 spec 把所有槽位都
        # 分给 product；调用方若需混合预算可通过 ``budget_spec`` 显式覆盖。
        if self._budget_spec is None:
            spec = ReferenceImageBudgetSpec(
                product_slots=max_total,
                character_slots=0,
                scene_slots=0,
                total_cap=max_total,
            )
        else:
            spec = self._budget_spec
        budget = ReferenceImageBudget(spec)
        result = budget.apply(
            product_refs=collected,
            max_total_override=max_total,
        )
        warnings.extend(result.warnings)
        return result.product_refs, warnings

    @staticmethod
    async def _resolve_linked_product_ids(
        db: AsyncSession,
        *,
        project_id: str,
        chapter_id: str,
        shot_id: str,
    ) -> list[str]:
        """按"最特定胜出"原则解析挂载商品 ID 列表。

        - shot 级匹配（``shot_id == this``）：最优先。
        - chapter 级匹配（``shot_id IS NULL AND chapter_id == this``）：次优先。
        - project 级匹配（``shot_id IS NULL AND chapter_id IS NULL``）：兜底。

        三档不合并；一旦更高精度有非空集合，就用该集合。
        """
        # shot-grain
        shot_stmt = (
            select(ProjectProductLink.product_id)
            .where(ProjectProductLink.project_id == project_id)
            .where(ProjectProductLink.shot_id == shot_id)
            .order_by(ProjectProductLink.id)
        )
        shot_rows = list((await db.execute(shot_stmt)).scalars().all())
        if shot_rows:
            return _dedup_preserve_order(shot_rows)

        # chapter-grain
        chapter_stmt = (
            select(ProjectProductLink.product_id)
            .where(ProjectProductLink.project_id == project_id)
            .where(ProjectProductLink.shot_id.is_(None))
            .where(ProjectProductLink.chapter_id == chapter_id)
            .order_by(ProjectProductLink.id)
        )
        chapter_rows = list((await db.execute(chapter_stmt)).scalars().all())
        if chapter_rows:
            return _dedup_preserve_order(chapter_rows)

        # project-grain
        project_stmt = (
            select(ProjectProductLink.product_id)
            .where(ProjectProductLink.project_id == project_id)
            .where(ProjectProductLink.shot_id.is_(None))
            .where(ProjectProductLink.chapter_id.is_(None))
            .order_by(ProjectProductLink.id)
        )
        project_rows = list((await db.execute(project_stmt)).scalars().all())
        return _dedup_preserve_order(project_rows)


def _dedup_preserve_order(values: list[str]) -> list[str]:
    """保留首次出现顺序的去重（同一商品在同一档可能挂多次）。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
