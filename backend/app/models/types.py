from __future__ import annotations

from enum import Enum


class ProjectStyle(str, Enum):
    """项目题材/风格维度（不用于区分真人/动漫）。"""

    # 真人：都市、科幻、古装；动漫：科幻、古装、3D、国漫、水墨画
    real_people_city = "真人都市"
    real_people_scifi = "真人科幻"
    real_people_ancient = "真人古装"
    anime_scifi = "动漫科幻"
    anime_3d = "动漫3D"
    guoman = "国漫"
    ink_wash = "水墨画"


class ProjectVisualStyle(str, Enum):
    """画面表现形式维度：用于区分现实/动漫等。"""

    live_action = "现实"
    anime = "动漫"


class ChapterStatus(str, Enum):
    """章节生产状态。"""

    draft = "draft"
    shooting = "shooting"
    done = "done"


class ShotStatus(str, Enum):
    """镜头生成状态（更多是“生产流程”而非剧情状态）。"""

    pending = "pending"
    generating = "generating"
    ready = "ready"


class ShotCandidateType(str, Enum):
    """镜头提取候选类型。"""

    character = "character"
    scene = "scene"
    prop = "prop"
    costume = "costume"


class ShotCandidateStatus(str, Enum):
    """镜头提取候选确认状态。"""

    pending = "pending"
    linked = "linked"
    ignored = "ignored"


class ShotDialogueCandidateStatus(str, Enum):
    """镜头对白提取候选确认状态。"""

    pending = "pending"
    accepted = "accepted"
    ignored = "ignored"


class CameraShotType(str, Enum):
    """景别（与 `app.schemas.skills.common.ShotType` 对齐，存英文 code）。"""

    ecu = "ECU"  # 大特写
    cu = "CU"  # 特写
    mcu = "MCU"  # 中近景
    ms = "MS"  # 中景
    mls = "MLS"  # 中远景
    ls = "LS"  # 远景
    els = "ELS"  # 大远景


class CameraAngle(str, Enum):
    """机位角度（与 `app.schemas.skills.common.CameraAngle` 对齐，存英文 code）。"""

    eye_level = "EYE_LEVEL"  # 平视
    high_angle = "HIGH_ANGLE"  # 高角度
    low_angle = "LOW_ANGLE"  # 低角度
    bird_eye = "BIRD_EYE"  # 鸟瞰
    dutch = "DUTCH"  # 荷兰式
    over_shoulder = "OVER_SHOULDER"  # 过肩


class CameraMovement(str, Enum):
    """运镜方式（与 `app.schemas.skills.common.CameraMovement` 对齐，存英文 code）。"""

    static = "STATIC"  # 静止
    pan = "PAN"  # 平移
    tilt = "TILT"  # 倾斜
    dolly_in = "DOLLY_IN"  # 拉近
    dolly_out = "DOLLY_OUT"  # 拉远
    track = "TRACK"  # 轨道
    crane = "CRANE"  # 摇臂
    handheld = "HANDHELD"  # 手持
    steadicam = "STEADICAM"  # 稳定器
    zoom_in = "ZOOM_IN"
    zoom_out = "ZOOM_OUT"  # 拉近


class AssetQualityLevel(str, Enum):
    """资产精度等级（由低到高逐步补齐更多角度/细节图）。"""

    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"
    ultra = "ULTRA"


class AssetViewAngle(str, Enum):
    """资产图片角度（用于多视图描述同一资产）。"""

    front = "FRONT"
    left = "LEFT"
    right = "RIGHT"
    back = "BACK"
    three_quarter = "THREE_QUARTER"
    top = "TOP"
    detail = "DETAIL"


class ShotFrameType(str, Enum):
    """镜头分镜帧类型：首帧/尾帧/关键帧。"""

    first = "first"
    last = "last"
    key = "key"


class FileType(str, Enum):
    """文件类型（用于素材库与时间线引用）。"""

    image = "image"
    video = "video"


class FileUsageKind(str, Enum):
    """文件在项目业务链上的用途（file_usages.usage_kind）。"""

    shot_frame = "shot_frame"
    generated_video = "generated_video"
    chapter_master_video = "chapter_master_video"
    character_image = "character_image"
    asset_image = "asset_image"
    task_link = "task_link"
    upload = "upload"
    api = "api"
    # === Story-Driven Commerce 扩展（P1）===
    product_image = "product_image"
    product_hero_shot = "product_hero_shot"
    commerce_reference = "commerce_reference"


class TimelineClipType(str, Enum):
    """时间线片段类型（视频/音频）。"""

    video = "video"
    audio = "audio"


class DialogueLineMode(str, Enum):
    """对白模式（与 `app.schemas.skills.common.DialogueLineMode` 对齐，存英文 code）。"""

    dialogue = "DIALOGUE"  # 对白
    voice_over = "VOICE_OVER"  # 旁白
    off_screen = "OFF_SCREEN"  # 画外音
    phone = "PHONE"  # 电话声


class VFXType(str, Enum):
    """视效类型（与 `app.schemas.skills.common.VFXType` 对齐，存英文 code）。"""

    none = "NONE"  # 无
    particles = "PARTICLES"  # 粒子
    volumetric_fog = "VOLUMETRIC_FOG"  # 体积雾
    cg_double = "CG_DOUBLE"  # 数字替身
    digital_environment = "DIGITAL_ENVIRONMENT"  # 数字场景
    matte_painting = "MATTE_PAINTING"  # 绘景
    fire_smoke = "FIRE_SMOKE"  # 烟火
    water_sim = "WATER_SIM"  # 水效
    destruction = "DESTRUCTION"  # 破碎/解算
    energy_magic = "ENERGY_MAGIC"  # 能量/魔法
    compositing_cleanup = "COMPOSITING_CLEANUP"  # 合成/修脏
    slow_motion_time = "SLOW_MOTION_TIME"  # 升格/慢动作
    other = "OTHER"  # 其他


class PromptCategory(str, Enum):
    """提示词模板类别。"""

    frame_head_image = "frame_head_image"
    frame_tail_image = "frame_tail_image"
    frame_key_image = "frame_key_image"
    frame_head_prompt = "frame_head_prompt"
    frame_tail_prompt = "frame_tail_prompt"
    frame_key_prompt = "frame_key_prompt"
    video_prompt = "video_prompt"
    storyboard_prompt = "storyboard_prompt"
    bgm = "bgm"
    sfx = "sfx"
    character_image_front = "character_image_front"
    character_image_other = "character_image_other"
    actor_image_front = "actor_image_front"
    actor_image_other = "actor_image_other"
    prop_image_front = "prop_image_front"
    prop_image_other = "prop_image_other"
    scene_image_front = "scene_image_front"
    scene_image_other = "scene_image_other"
    costume_image_front = "costume_image_front"
    costume_image_other = "costume_image_other"
    combined = "combined"
    # === Story-Driven Commerce 扩展（P1）===
    product_extraction = "product_extraction"
    story_formula_generator = "story_formula_generator"
    hook_pattern_writer = "hook_pattern_writer"
    cta_pattern_writer = "cta_pattern_writer"
    archetype_voice_rewriter = "archetype_voice_rewriter"
    compliance_checker = "compliance_checker"
    product_image_front = "product_image_front"
    product_image_other = "product_image_other"
    product_placement_prompt = "product_placement_prompt"
    product_hero_prompt = "product_hero_prompt"
    audience_insight = "audience_insight"
    brand_voice_profile = "brand_voice_profile"


# === Story-Driven Commerce Enums (P1) ===


class ProjectKind(str, Enum):
    """项目业务类型：区分普通短剧与剧情带货项目。

    用于 Project.kind 字段，决定项目走"剧情"还是"剧情带货"流程；
    默认 drama 保持向后兼容，commerce_story 启用商品/合规/受众等扩展能力。
    """

    drama = "drama"
    commerce_story = "commerce_story"


class ProductCategory(str, Enum):
    """商品品类：用于在带货项目中标识商品所属行业。

    影响合规规则（如 health 触发免责声明要求）与故事公式选择；
    覆盖电子/美妆/食品/服饰/家居/健康及其他兜底类。
    """

    electronics = "electronics"
    beauty = "beauty"
    food = "food"
    apparel = "apparel"
    home = "home"
    health = "health"
    other = "other"


class FormulaRegion(str, Enum):
    """故事公式所属地区取向：决定可选的叙事框架集合。

    cn 对应中国市场常用的"凡人逆袭/打脸"等公式；
    global 对应西方框架（Hero's Journey 等）。
    """

    cn = "cn"
    global_ = "global"


class ComplianceRegion(str, Enum):
    """合规检查目标地区：不同地区有不同的禁用词与必备标识。

    用于剧情带货脚本/视频在发布前的合规校验，按地区切换规则集。
    """

    cn_mainland = "cn_mainland"
    hk_tw = "hk_tw"
    overseas = "overseas"


class ComplianceSeverity(str, Enum):
    """合规问题严重等级：决定是否阻塞发布。

    info 仅提示；warning 需关注；blocker 必须修复才能继续。
    """

    info = "info"
    warning = "warning"
    blocker = "blocker"


class StoryVariantStatus(str, Enum):
    """故事变体（Story Variant）的生命周期状态。

    用于剧情带货中同一商品/受众生成多版剧本/视频时跟踪每个变体的处理阶段。
    """

    draft = "draft"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class ProductRoleInStory(str, Enum):
    """商品在故事中扮演的叙事角色。

    用于指导脚本生成时如何嵌入商品；非纯广告，而是把商品融入剧情的关键点
    （拯救者 / 催化剂 / 冲突源 / 彩蛋 / 主角同伴）。
    """

    savior = "savior"
    catalyst = "catalyst"
    conflict_source = "conflict_source"
    easter_egg = "easter_egg"
    protagonist_companion = "protagonist_companion"


class ProductAppearanceTiming(str, Enum):
    """商品在剧情时间线上的出现时机。

    用于控制带货节奏：开场 / 中段 / 高潮 / 结尾，影响转化率与观看体验。
    """

    opening = "opening"
    middle = "middle"
    climax = "climax"
    ending = "ending"


class Platform(str, Enum):
    """目标投放平台：决定时长、画幅与合规策略的差异化。

    覆盖国内主流（抖音/快手/小红书）与海外（YouTube/TikTok）。
    """

    douyin = "douyin"
    kuaishou = "kuaishou"
    xiaohongshu = "xiaohongshu"
    youtube = "youtube"
    tiktok = "tiktok"


# === Story-Driven Commerce Enums (P2) ===


class BrandArchetype(str, Enum):
    """品牌人格原型 — 12 个 archetype 来自 tonethief 标准词汇表。

    P2 启用：用于 commerce_story_configs.archetype + StoryVariant.archetype + ArchetypeVoiceRewriterAgent。
    """

    sage = "sage"               # 智者 — 知识/智慧
    jester = "jester"           # 小丑 — 幽默/活力
    rebel = "rebel"             # 反叛者 — 颠覆/独立
    provocateur = "provocateur" # 挑衅者 — 争议/惊艳
    maverick = "maverick"       # 独行者 — 个性/自由
    friend = "friend"           # 朋友 — 亲切/陪伴
    expert = "expert"           # 专家 — 权威/精确
    cheerleader = "cheerleader" # 鼓励者 — 振奋/动力
    storyteller = "storyteller" # 说书人 — 叙事/想象
    analyst = "analyst"         # 分析师 — 理性/数据
    coach = "coach"             # 教练 — 引导/激励
    minimalist = "minimalist"   # 极简主义 — 简洁/纯粹


class ToneDimension(str, Enum):
    """语调维度 — 每个维度 0-10 分，配合 BrandArchetype 形成 tone_grid。

    参考: tonethief 的 10 维度模型。
    """

    formality = "formality"           # Formal ↔ Casual
    seriousness = "seriousness"       # Serious ↔ Playful
    technicality = "technicality"     # Technical ↔ Accessible
    enthusiasm = "enthusiasm"         # Reserved ↔ Enthusiastic
    humanity = "humanity"             # Corporate ↔ Human
    activity = "activity"             # Passive ↔ Active
    specificity = "specificity"       # Vague ↔ Specific
    conciseness = "conciseness"       # Long-winded ↔ Concise
    conventionality = "conventionality"  # Conventional ↔ Irreverent
    safety = "safety"                 # Safe ↔ Provocative
