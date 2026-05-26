from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import ShotFrameImage, ShotFrameType
from app.services.studio.generation.shared.types import GenerationContext

REQUIRED_FRAMES_BY_MODE: dict[str, tuple[ShotFrameType, ...]] = {
    "first": (ShotFrameType.first,),
    "last": (ShotFrameType.last,),
    "key": (ShotFrameType.key,),
    "first_last": (ShotFrameType.first, ShotFrameType.last),
    "first_last_key": (ShotFrameType.first, ShotFrameType.last, ShotFrameType.key),
    "text_only": (),
    # multi_ref: 商品多图参考模式。空 tuple 含义与 text_only 不同——参考图来源于
    # ProductImage（由 build_run_args 调用 ShotProductReferenceResolver 提前解析），
    # 而非 ShotFrameImage。校验路径需特判。
    "multi_ref": (),
}

MULTI_REF_MIN_COUNT = 1
MULTI_REF_DEFAULT_CAP = 9


def required_image_count(reference_mode: str) -> int:
    return len(REQUIRED_FRAMES_BY_MODE[reference_mode])


def validate_images_count(reference_mode: str, images: list[str]) -> None:
    """校验 reference_mode 与 images 数量是否匹配。

    multi_ref 特判：要求 1..MULTI_REF_DEFAULT_CAP（9）张；其它模式按 frame_map 严格相等。
    """
    actual = len(images or [])
    if reference_mode == "multi_ref":
        if actual < MULTI_REF_MIN_COUNT or actual > MULTI_REF_DEFAULT_CAP:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"reference_mode=multi_ref requires {MULTI_REF_MIN_COUNT}..{MULTI_REF_DEFAULT_CAP} "
                    f"images, got {actual}"
                ),
            )
        return
    expected = required_image_count(reference_mode)
    if actual != expected:
        raise HTTPException(
            status_code=400,
            detail=f"reference_mode={reference_mode} requires exactly {expected} images, got {actual}",
        )


async def resolve_video_reference_images(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None = None,
) -> list[str]:
    """解析视频生成参考图。

    multi_ref 由 build_run_args 提前调用 ShotProductReferenceResolver 解析，
    本函数只负责直通已解析的列表（保持 build_context 层无 commerce 域依赖）。
    """
    normalized = [str(item).strip() for item in (images or []) if str(item).strip()]
    if reference_mode == "multi_ref":
        return normalized

    if normalized:
        validate_images_count(reference_mode, normalized)
        return normalized

    required_frames = REQUIRED_FRAMES_BY_MODE[reference_mode]
    if not required_frames:
        return []

    stmt = select(ShotFrameImage).where(
        ShotFrameImage.shot_detail_id == shot_id,
        ShotFrameImage.frame_type.in_(required_frames),
    )
    rows = (await db.execute(stmt)).scalars().all()
    frame_map = {row.frame_type: row for row in rows}

    missing: list[ShotFrameType] = []
    ordered_images: list[str] = []
    for frame_type in required_frames:
        row = frame_map.get(frame_type)
        if row is None or not row.file_id:
            missing.append(frame_type)
            continue
        ordered_images.append(str(row.file_id))

    if missing:
        missing_name = ",".join(item.value for item in missing)
        raise HTTPException(
            status_code=400,
            detail=f"Required frame image is missing: {missing_name}; please generate it first",
        )
    return ordered_images


class VideoGenerationContext(GenerationContext):
    """视频生成的动态上下文。"""

    kind: str = "video"
    shot_id: str
    reference_mode: str
    images: list[str]
    template_id: str | None = None


async def build_video_context(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None,
    template_id: str | None = None,
) -> VideoGenerationContext:
    resolved_images = await resolve_video_reference_images(
        db,
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=images,
    )
    return VideoGenerationContext(
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=resolved_images,
        template_id=template_id,
    )

