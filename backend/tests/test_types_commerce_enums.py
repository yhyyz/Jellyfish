"""W1-T1 验收测试：剧情带货枚举扩展。

验证 backend/app/models/types.py 中：
1. 8 个新增枚举类可导入、成员数与值正确；
2. FileUsageKind / PromptCategory 在新增值后仍保留全部原有值（向后兼容）。
"""

from __future__ import annotations

from enum import Enum

from app.models.types import (
    BrandArchetype,
    ComplianceRegion,
    ComplianceSeverity,
    FileUsageKind,
    FormulaRegion,
    Platform,
    ProductAppearanceTiming,
    ProductCategory,
    ProductRoleInStory,
    ProjectKind,
    PromptCategory,
    StoryVariantStatus,
    ToneDimension,
)


def _values(enum_cls: type[Enum]) -> set[str]:
    """提取枚举 value 集合，便于断言成员归属。"""
    return {str(member.value) for member in enum_cls}


# ---------- 新增枚举：成员计数 ----------


def test_project_kind_members() -> None:
    assert _values(ProjectKind) == {"drama", "commerce_story"}


def test_product_category_members() -> None:
    assert _values(ProductCategory) == {
        "electronics",
        "beauty",
        "food",
        "apparel",
        "home",
        "health",
        "other",
    }
    assert len(ProductCategory) == 7


def test_formula_region_members() -> None:
    # global 是 Python 关键字，类成员名为 global_，值仍为 "global"
    assert _values(FormulaRegion) == {"cn", "global"}
    assert FormulaRegion.global_.value == "global"


def test_compliance_region_members() -> None:
    assert _values(ComplianceRegion) == {"cn_mainland", "hk_tw", "overseas"}


def test_compliance_severity_members() -> None:
    assert _values(ComplianceSeverity) == {"info", "warning", "blocker"}


def test_story_variant_status_members() -> None:
    assert _values(StoryVariantStatus) == {"draft", "generating", "ready", "failed"}


def test_product_role_in_story_members() -> None:
    assert _values(ProductRoleInStory) == {
        "savior",
        "catalyst",
        "conflict_source",
        "easter_egg",
        "protagonist_companion",
    }
    assert len(ProductRoleInStory) == 5


def test_product_appearance_timing_members() -> None:
    assert _values(ProductAppearanceTiming) == {"opening", "middle", "climax", "ending"}


def test_platform_members() -> None:
    assert _values(Platform) == {"douyin", "kuaishou", "xiaohongshu", "youtube", "tiktok"}
    assert len(Platform) == 5


# ---------- 扩展枚举：原值保留 + 新值加入 ----------


_FILE_USAGE_LEGACY = {
    "shot_frame",
    "generated_video",
    "chapter_master_video",
    "character_image",
    "asset_image",
    "task_link",
    "upload",
    "api",
}
_FILE_USAGE_NEW = {"product_image", "product_hero_shot", "commerce_reference"}
# P3 W17 引入的 TTS / 音轨用途（tts_audio / bgm_track / sfx_track）。
_FILE_USAGE_AUDIO_W17 = {"tts_audio", "bgm_track", "sfx_track"}
# P3 W19 引入的章节级 AV 合成产物（master audio / subtitle / dubbed video）。
_FILE_USAGE_CHAPTER_AV_W19 = {
    "chapter_master_audio",
    "chapter_master_subtitle",
    "chapter_master_dubbed",
}


def test_file_usage_kind_preserves_legacy_values() -> None:
    """FileUsageKind 必须保留全部 8 个原值。"""
    assert _FILE_USAGE_LEGACY.issubset(_values(FileUsageKind))


def test_file_usage_kind_adds_commerce_values() -> None:
    """FileUsageKind 应新增 3 个商品相关用途。"""
    assert _FILE_USAGE_NEW.issubset(_values(FileUsageKind))


def test_file_usage_kind_total_count() -> None:
    """FileUsageKind 总数 = legacy + commerce(P1) + W17 audio + W19 chapter AV。"""
    assert len(FileUsageKind) == (
        len(_FILE_USAGE_LEGACY)
        + len(_FILE_USAGE_NEW)
        + len(_FILE_USAGE_AUDIO_W17)
        + len(_FILE_USAGE_CHAPTER_AV_W19)
    )


_PROMPT_CATEGORY_LEGACY = {
    "frame_head_image",
    "frame_tail_image",
    "frame_key_image",
    "frame_head_prompt",
    "frame_tail_prompt",
    "frame_key_prompt",
    "video_prompt",
    "storyboard_prompt",
    "bgm",
    "sfx",
    "character_image_front",
    "character_image_other",
    "actor_image_front",
    "actor_image_other",
    "prop_image_front",
    "prop_image_other",
    "scene_image_front",
    "scene_image_other",
    "costume_image_front",
    "costume_image_other",
    "combined",
}
_PROMPT_CATEGORY_NEW = {
    "product_extraction",
    "story_formula_generator",
    "hook_pattern_writer",
    "cta_pattern_writer",
    "archetype_voice_rewriter",
    "compliance_checker",
    "product_image_front",
    "product_image_other",
    "product_placement_prompt",
    "product_hero_prompt",
    "audience_insight",
    "brand_voice_profile",
}


def test_prompt_category_preserves_legacy_values() -> None:
    """PromptCategory 必须保留全部 21 个原值。"""
    assert _PROMPT_CATEGORY_LEGACY.issubset(_values(PromptCategory))
    assert len(_PROMPT_CATEGORY_LEGACY) == 21


def test_prompt_category_adds_commerce_values() -> None:
    """PromptCategory 应新增 12 个商品/剧情带货相关类别。"""
    assert _PROMPT_CATEGORY_NEW.issubset(_values(PromptCategory))
    assert len(_PROMPT_CATEGORY_NEW) == 12


def test_prompt_category_total_count() -> None:
    assert len(PromptCategory) == len(_PROMPT_CATEGORY_LEGACY) + len(_PROMPT_CATEGORY_NEW)


# ---------- str-Enum 行为：所有新增枚举都是 str 子类 ----------


def test_new_enums_are_str_subclasses() -> None:
    """所有新增枚举必须为 (str, Enum)，与现有约定一致。"""
    for cls in (
        ProjectKind,
        ProductCategory,
        FormulaRegion,
        ComplianceRegion,
        ComplianceSeverity,
        StoryVariantStatus,
        ProductRoleInStory,
        ProductAppearanceTiming,
        Platform,
    ):
        member = next(iter(cls))
        assert isinstance(member, str), f"{cls.__name__} member is not str subclass"


# ---------- P2 新增枚举：BrandArchetype + ToneDimension ----------


_BRAND_ARCHETYPE_VALUES = {
    "sage",
    "jester",
    "rebel",
    "provocateur",
    "maverick",
    "friend",
    "expert",
    "cheerleader",
    "storyteller",
    "analyst",
    "coach",
    "minimalist",
}


_TONE_DIMENSION_VALUES = {
    "formality",
    "seriousness",
    "technicality",
    "enthusiasm",
    "humanity",
    "activity",
    "specificity",
    "conciseness",
    "conventionality",
    "safety",
}


def test_brand_archetype_enum_has_12_members() -> None:
    """BrandArchetype 必须包含 12 个 tonethief 标准 archetype。"""
    assert len(BrandArchetype) == 12
    assert _values(BrandArchetype) == _BRAND_ARCHETYPE_VALUES


def test_brand_archetype_values_are_lowercase_snake_case() -> None:
    """所有 archetype 值必须为 lowercase（无大写、无空格、无连字符）。"""
    for member in BrandArchetype:
        value = str(member.value)
        assert value == value.lower(), f"{member.name} value not lowercase: {value}"
        assert " " not in value, f"{member.name} value has space: {value}"
        assert "-" not in value, f"{member.name} value has hyphen: {value}"


def test_brand_archetype_specific_members_exist() -> None:
    """显式断言 12 个 archetype 成员均可访问。"""
    assert BrandArchetype.sage.value == "sage"
    assert BrandArchetype.jester.value == "jester"
    assert BrandArchetype.rebel.value == "rebel"
    assert BrandArchetype.provocateur.value == "provocateur"
    assert BrandArchetype.maverick.value == "maverick"
    assert BrandArchetype.friend.value == "friend"
    assert BrandArchetype.expert.value == "expert"
    assert BrandArchetype.cheerleader.value == "cheerleader"
    assert BrandArchetype.storyteller.value == "storyteller"
    assert BrandArchetype.analyst.value == "analyst"
    assert BrandArchetype.coach.value == "coach"
    assert BrandArchetype.minimalist.value == "minimalist"


def test_tone_dimension_enum_has_10_members() -> None:
    """ToneDimension 必须包含 10 个 tonethief 维度。"""
    assert len(ToneDimension) == 10
    assert _values(ToneDimension) == _TONE_DIMENSION_VALUES


def test_tone_dimension_values_match_tonethief_taxonomy() -> None:
    """显式断言 10 个 ToneDimension 成员名称与 tonethief 词表对齐。"""
    assert ToneDimension.formality.value == "formality"
    assert ToneDimension.seriousness.value == "seriousness"
    assert ToneDimension.technicality.value == "technicality"
    assert ToneDimension.enthusiasm.value == "enthusiasm"
    assert ToneDimension.humanity.value == "humanity"
    assert ToneDimension.activity.value == "activity"
    assert ToneDimension.specificity.value == "specificity"
    assert ToneDimension.conciseness.value == "conciseness"
    assert ToneDimension.conventionality.value == "conventionality"
    assert ToneDimension.safety.value == "safety"


def test_p2_enums_are_str_subclasses() -> None:
    """BrandArchetype + ToneDimension 必须为 (str, Enum) 子类。"""
    for cls in (BrandArchetype, ToneDimension):
        member = next(iter(cls))
        assert isinstance(member, str), f"{cls.__name__} member is not str subclass"
