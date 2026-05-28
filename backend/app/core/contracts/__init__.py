"""生成任务共享契约导出。"""

from app.core.contracts.image_generation import (
    ImageGenerationInput,
    ImageGenerationResult,
    ImageItem,
    InputImageRef,
    ResponseFormat,
)
from app.core.contracts.provider import ProviderConfig, ProviderKey
from app.core.contracts.story import (
    BrandVoice,
    ComplianceFinding,
    ComplianceReport,
    ProductExtractionResult,
    Shot,
    StoryGenerationVars,
    StoryScript,
)
from app.core.contracts.tts import (
    TtsCacheKey,
    TtsRequest,
    TtsResult,
    TtsVoiceCapability,
    TtsWordTimestamp,
)
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult
from app.core.contracts.voice_pack_contracts import (
    ALLOWED_AUDIO_FORMATS,
    ALLOWED_TARGET_MODELS,
    AudioMetadataValidation,
    CustomVoiceCreateRequest,
    CustomVoiceCreateResponse,
    CustomVoiceStatusResponse,
)

__all__ = [
    "ProviderConfig",
    "ProviderKey",
    "VideoGenerationInput",
    "VideoGenerationResult",
    "ImageGenerationInput",
    "ImageGenerationResult",
    "ImageItem",
    "InputImageRef",
    "ResponseFormat",
    "Shot",
    "StoryScript",
    "StoryGenerationVars",
    "ProductExtractionResult",
    "ComplianceFinding",
    "ComplianceReport",
    "BrandVoice",
    "TtsRequest",
    "TtsResult",
    "TtsWordTimestamp",
    "TtsCacheKey",
    "TtsVoiceCapability",
    "ALLOWED_AUDIO_FORMATS",
    "ALLOWED_TARGET_MODELS",
    "AudioMetadataValidation",
    "CustomVoiceCreateRequest",
    "CustomVoiceCreateResponse",
    "CustomVoiceStatusResponse",
]

