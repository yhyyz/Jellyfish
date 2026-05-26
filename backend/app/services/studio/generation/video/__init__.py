"""视频生成准备服务。"""

from app.services.studio.generation.video.build_base import VideoBaseDraft, build_video_base_draft
from app.services.studio.generation.video.build_context import (
    MULTI_REF_DEFAULT_CAP,
    MULTI_REF_MIN_COUNT,
    REQUIRED_FRAMES_BY_MODE,
    VideoGenerationContext,
    build_video_context,
    required_image_count,
    resolve_video_reference_images,
    validate_images_count,
)
from app.services.studio.generation.video.build_submission import build_video_submission_payload
from app.services.studio.generation.video.derive_preview import VideoDerivedPreview, derive_video_preview
from app.services.studio.generation.video.shot_product_reference_resolver import (
    PRIORITY_BY_FOCUS_LEVEL,
    ShotProductReferenceResolver,
)

__all__ = [
    "MULTI_REF_DEFAULT_CAP",
    "MULTI_REF_MIN_COUNT",
    "PRIORITY_BY_FOCUS_LEVEL",
    "REQUIRED_FRAMES_BY_MODE",
    "ShotProductReferenceResolver",
    "VideoBaseDraft",
    "VideoDerivedPreview",
    "VideoGenerationContext",
    "build_video_base_draft",
    "build_video_context",
    "build_video_submission_payload",
    "derive_video_preview",
    "required_image_count",
    "resolve_video_reference_images",
    "validate_images_count",
]

