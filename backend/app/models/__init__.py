"""SQLAlchemy ORM 模型。"""

from app.core.db import Base
from app.models.api_quota import ApiKeyQuota
from app.models.base import TimestampMixin
from app.models.brand_archetype import BrandArchetype
from app.models.compliance import ComplianceFinding, ComplianceProfile
from app.models.cta_pattern import CtaPattern
from app.models.hook_pattern import HookPattern
from app.models.llm import Model, ModelSettings, Provider
from app.models.story_formula import StoryFormula, StoryOutcome, StoryVariant
from app.models.subtitle import SubtitleStyle, SubtitleTrack
from app.models.task import GenerationTask
from app.models.task_links import GenerationTaskLink
from app.models.types import FileUsageKind
from app.models.voice_pack import TtsCache, VoicePack

from app.models.studio import (
    Actor,
    ActorImage,
    Chapter,
    Character,
    CharacterImage,
    CharacterPropLink,
    CommerceStoryConfig,
    Costume,
    CostumeImage,
    FileItem,
    FileUsage,
    Product,
    ProductImage,
    Project,
    ProjectProductLink,
    Prop,
    PropImage,
    PromptTemplate,
    Scene,
    SceneImage,
    Shot,
    ShotCharacterLink,
    ShotDetail,
    ShotDialogLine,
    ShotFrameImage,
    ShotFrameType,
    ProjectActorLink,
    ProjectCostumeLink,
    ProjectPropLink,
    ProjectSceneLink,
    TimelineClip,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "Project",
    "Chapter",
    "Shot",
    "ShotDetail",
    "ShotDialogLine",
    "ShotFrameImage",
    "ShotFrameType",
    "ProjectActorLink",
    "ProjectSceneLink",
    "ProjectPropLink",
    "ProjectCostumeLink",
    "ShotCharacterLink",
    "Actor",
    "Character",
    "CharacterImage",
    "CharacterPropLink",
    "ActorImage",
    "Scene",
    "SceneImage",
    "Prop",
    "PropImage",
    "Costume",
    "CostumeImage",
    "PromptTemplate",
    "FileItem",
    "FileUsage",
    "FileUsageKind",
    "TimelineClip",
    "Provider",
    "Model",
    "ModelSettings",
    "GenerationTask",
    "GenerationTaskLink",
    "ComplianceProfile",
    "ComplianceFinding",
    "StoryFormula",
    "StoryVariant",
    "StoryOutcome",
    "HookPattern",
    "CtaPattern",
    "BrandArchetype",
    "Product",
    "ProductImage",
    "ProjectProductLink",
    "CommerceStoryConfig",
    "VoicePack",
    "TtsCache",
    "SubtitleStyle",
    "SubtitleTrack",
]
