"""分镜视觉一致性证据服务（W27-T3，只读）。

职责：

1. 加载 :class:`Shot`（不存在抛 404）；
2. 复用 W27-T1 worker 一致的 ProductImage 反查路径（``Shot → Chapter →
   ProjectProductLink → Product → ProductImage``）取多角度图片；
3. 把 ``Shot.consistency_score`` 映射成色档状态字面量；
4. 拼装可被 :class:`ConsistencyEvidenceRead` 直接消费的 dict。

设计要点：

- **只读，不重新计算 score**：W27-T1 已经把 score 持久化到 DB，本服务严
  禁触达 sidecar / ffmpeg。
- **样本来源**：worker 当前不持久化 ffmpeg 抽帧产物，因此从关联 product
  的 ProductImage 拼装最多 6 张作为视觉证据样本；reference 与样本可重
  叠（前端 PreviewGroup 不去重，提供同一切面的 cross-reference）。
- **避免 race**：本服务只 query，不写库；与 T27-1 / T27-2 worker 并发安全。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import _build_public_url  # pylint: disable=protected-access
from app.models.commerce_assets import ProductImage, ProjectProductLink
from app.models.studio_prompts_files_timeline import FileItem
from app.models.studio_projects import Chapter
from app.models.studio_shots import Shot
from app.models.types import AssetViewAngle
from app.schemas.commerce.shot_consistency import ConsistencyStatus

#: 与 ConsistencyBadge 阈值同源；调整时务必同步前端 components/ConsistencyBadge.tsx。
SCORE_THRESHOLD_GREEN: float = 0.85
SCORE_THRESHOLD_AMBER: float = 0.75

#: 样本帧数量上限：与前端 PreviewGroup 横向 6 张同步。
MAX_SAMPLED_FRAMES: int = 6

#: 与 worker 完全一致的参考图视角优先级。
_REFERENCE_VIEW_ANGLE_FALLBACK: tuple[AssetViewAngle, ...] = (
    AssetViewAngle.front,
    AssetViewAngle.three_quarter,
)


def derive_status(score: float | None) -> ConsistencyStatus:
    """根据数值得到色档状态字面量。

    阈值与 :data:`SCORE_THRESHOLD_GREEN` / :data:`SCORE_THRESHOLD_AMBER`
    保持单一真相来源；前端 ``ConsistencyBadge`` 必须使用同一组阈值。
    """

    if score is None:
        return "unknown"
    if score >= SCORE_THRESHOLD_GREEN:
        return "green"
    if score >= SCORE_THRESHOLD_AMBER:
        return "amber"
    return "red"


async def _resolve_product_id_for_shot(
    session: AsyncSession,
    *,
    shot_id: str,
    chapter_id: str,
    project_id: str,
) -> str | None:
    """按 shot → chapter → project 三级粒度找 ProjectProductLink.product_id。

    与 worker ``_resolve_product_id_for_shot`` 行为一致；这里再实现一遍而
    非直接 import，避免暴露 worker 私有 API（worker 模块依赖 ffmpeg 等
    重资源，路由层 import 会拖慢冷启动）。
    """

    # Shot 级。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.shot_id == shot_id,
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id

    # Chapter 级（shot_id 为空）。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.chapter_id == chapter_id,
        ProjectProductLink.shot_id.is_(None),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id

    # Project 级（chapter / shot 都空）。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.chapter_id.is_(None),
        ProjectProductLink.shot_id.is_(None),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id
    return None


async def _resolve_reference_image(
    session: AsyncSession, *, product_id: str
) -> tuple[FileItem | None, AssetViewAngle | None]:
    """按 FRONT / THREE_QUARTER 优先级找参考图 FileItem。

    与 worker ``_resolve_reference_image`` 同源逻辑；缺图返回 ``(None, None)``。
    """

    for angle in _REFERENCE_VIEW_ANGLE_FALLBACK:
        stmt = (
            select(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.view_angle == angle,
                ProductImage.file_id.is_not(None),
            )
            .order_by(ProductImage.is_primary.desc(), ProductImage.id.asc())
        )
        product_image = (await session.execute(stmt)).scalars().first()
        if product_image is None or product_image.file_id is None:
            continue
        file_obj = await session.get(FileItem, product_image.file_id)
        if file_obj is not None and file_obj.storage_key:
            return file_obj, angle
    return None, None


async def _list_sampled_files(
    session: AsyncSession, *, product_id: str, limit: int = MAX_SAMPLED_FRAMES
) -> list[FileItem]:
    """列出 product 下所有可作为视觉证据样本的 FileItem，最多 ``limit`` 张。

    选取策略：``is_primary DESC`` + ``id ASC``，与现有 ProductImage 列表
    其它接口的稳定排序保持一致；保证主图永远落在样本第一张。
    """

    stmt = (
        select(ProductImage)
        .where(
            ProductImage.product_id == product_id,
            ProductImage.file_id.is_not(None),
        )
        .order_by(ProductImage.is_primary.desc(), ProductImage.id.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    files: list[FileItem] = []
    for row in rows:
        if row.file_id is None:
            continue
        file_obj = await session.get(FileItem, row.file_id)
        if file_obj is not None and file_obj.storage_key:
            files.append(file_obj)
    return files


async def build_consistency_evidence(
    session: AsyncSession, *, shot_id: str
) -> dict[str, Any]:
    """组装一致性证据响应字典。

    不存在 Shot 时返回 ``None`` —— 由路由层翻译成 404。本函数刻意不抛
    HTTPException，让 service 层与 web 层解耦。
    """

    shot = await session.get(Shot, shot_id)
    if shot is None:
        raise LookupError(f"Shot not found: {shot_id}")

    score = shot.consistency_score
    status = derive_status(score)

    # 解析关联 product，缺关联时直接走空态（status 仍按 score 走）。
    chapter = await session.get(Chapter, shot.chapter_id)
    product_id: str | None = None
    if chapter is not None:
        product_id = await _resolve_product_id_for_shot(
            session,
            shot_id=shot.id,
            chapter_id=shot.chapter_id,
            project_id=chapter.project_id,
        )

    sampled_urls: list[str] = []
    reference_url: str | None = None
    reference_view_angle: str | None = None

    if product_id is not None:
        reference_file, ref_angle = await _resolve_reference_image(
            session, product_id=product_id
        )
        if reference_file is not None:
            reference_url = _build_public_url(reference_file.storage_key)
        if ref_angle is not None:
            reference_view_angle = ref_angle.value

        sampled_files = await _list_sampled_files(session, product_id=product_id)
        sampled_urls = [
            _build_public_url(file_obj.storage_key) for file_obj in sampled_files
        ]

    # T27-2 retry 字段未落 model 时保持 None；getattr 兜底以容忍并行 wave 落字段。
    retry_count = getattr(shot, "retry_count", None)

    return {
        "shot_id": shot.id,
        "score": score,
        "status": status,
        "sampled_frame_urls": sampled_urls,
        "reference_image_url": reference_url,
        "reference_view_angle": reference_view_angle,
        "retry_count": retry_count,
    }


__all__ = [
    "build_consistency_evidence",
    "derive_status",
    "MAX_SAMPLED_FRAMES",
    "SCORE_THRESHOLD_AMBER",
    "SCORE_THRESHOLD_GREEN",
]
