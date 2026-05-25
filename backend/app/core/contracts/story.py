"""故事驱动型电商（story-driven commerce）核心 DTO 契约。

本模块定义 Wave 1 阶段的共享数据契约，被 Wave 4 的 Agent 与 Wave 6 的 API
端点消费。所有模型遵循 Pydantic v2 规范，并对参与 OpenAI structured output
的字段使用 ``Optional[X] = None`` 而非 ``Field(default=...)`` 以兼容
``json_schema`` strict 模式（参见 issues.md I8 与 decisions.md D5）。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# StoryScript 相关
# ---------------------------------------------------------------------------


class Shot(BaseModel):
    """脚本中的单个镜头。

    描述一镜的时长、功能定位、镜头语言、对白/旁白以及与商品/品牌的关系，
    供 ``StoryScriptGeneratorAgent`` 输出，并由后续视频生成流程消费。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="镜头唯一标识，如 shot_001")
    duration_sec: float = Field(
        ...,
        ge=2,
        le=20,
        description="该镜头的时长（秒），区间 [2, 20]",
    )
    function: str = Field(..., description="镜头在脚本中的功能定位（hook / setup / payoff 等）")
    shot_type: str = Field(..., description="镜头景别，如 close_up / medium / wide")
    camera_angle: str = Field(..., description="机位/角度，如 eye_level / high_angle")
    camera_movement: str = Field(..., description="运镜方式，如 static / push_in / handheld")
    dialog: Optional[str] = Field(None, description="角色对白文本；无对白时为 None")
    narration: Optional[str] = Field(None, description="旁白文本；无旁白时为 None")
    product_focus_level: Literal["subtle", "functional", "hero", "none"] = Field(
        ...,
        description="商品出现层级：subtle / functional / hero / none",
    )
    is_punchline: bool = Field(..., description="是否为情绪/反转 punchline 镜头")
    is_brand_mention: bool = Field(..., description="是否包含品牌口播")
    notes: Optional[str] = Field(None, description="导演/制作备注，可为空")


class StoryScript(BaseModel):
    """完整故事脚本，``StoryScriptGeneratorAgent`` 的输出契约。

    聚合了一组 ``Shot``，并在顶层暴露总时长、镜头总数、所用公式、
    开场钩子、CTA 文案与品牌口播次数等关键统计字段，供合规校验与
    任务编排使用。
    """

    model_config = ConfigDict(extra="forbid")

    total_duration_sec: float = Field(..., description="脚本总时长（秒）")
    total_shots: int = Field(..., description="脚本镜头总数")
    formula_id: str = Field(..., description="所采用的故事公式 ID")
    shots: list[Shot] = Field(
        ...,
        min_length=3,
        max_length=30,
        description="镜头列表，长度区间 [3, 30]",
    )
    opening_hook: str = Field(..., description="开场钩子文案，用于评估前 3 秒留存")
    cta_text: str = Field(..., description="结尾 Call-To-Action 文案")
    brand_mention_count: int = Field(..., description="脚本中品牌口播出现次数")


class StoryGenerationVars(BaseModel):
    """``story_formula_generator`` Jinja 提示词的输入变量契约。

    封装公式、商品、受众、原型、tone grid、目标时长与平台等渲染所需上下文，
    用于驱动 LLM 生成符合公式约束的脚本。
    """

    model_config = ConfigDict(extra="forbid")

    formula: dict = Field(..., description="故事公式结构，包含节拍/约束/示例")
    product: dict = Field(..., description="商品信息（来自 ProductExtractionResult 序列化）")
    audience: dict = Field(..., description="目标受众画像")
    archetype: str = Field(..., description="品牌人格原型，如 hero / sage / jester")
    tone_grid: dict = Field(..., description="调性网格：正式度/能量/温度/幽默等维度")
    target_duration_sec: int = Field(
        ...,
        ge=15,
        le=180,
        description="目标脚本时长（秒），区间 [15, 180]",
    )
    platform: str = Field(..., description="目标投放平台，如 douyin / tiktok / reels")


# ---------------------------------------------------------------------------
# 前 3 秒钩子（HookWriterAgent）
# ---------------------------------------------------------------------------


class ShotHook(BaseModel):
    """前 3 秒钩子文本输出 —— ``HookWriterAgent`` 的产出。

    用于对 ``StoryScript.opening_hook`` 字段做单独优化（A/B 测试或 refinement），
    与脚本主流程解耦：generator 已生成基础钩子，本结构作为可替换候选。
    """

    model_config = ConfigDict(extra="forbid")

    hook_text: str = Field(
        ...,
        min_length=4,
        max_length=80,
        description="前 3 秒钩子文本（中文，建议 ≤30 字）",
    )
    pattern_id: str = Field(..., description="使用的 hook_pattern ID")
    pattern_type: str = Field(
        ...,
        description="模式分类：question/conflict/contrast/numerical/curiosity/...",
    )
    rationale: Optional[str] = Field(
        None,
        description="为什么选择这个钩子的简要解释；可为空",
    )


class HookWriteVars(BaseModel):
    """``HookWriterAgent`` 的输入变量契约。

    与 ``hook_pattern_writer_v1`` 模板对齐：模板暴露 ``pattern_id`` /
    ``product`` / ``audience`` 三个 jinja 变量，本结构在 Agent 入口侧拆分得
    更细，便于 worker / API 层组装；Agent 内部再合成模板所需 dict。
    """

    model_config = ConfigDict(extra="forbid")

    pattern_id: str = Field(..., description="目标 hook 模式 ID")
    pattern_type: str = Field(
        ...,
        description="模式分类，需与 ShotHook.pattern_type 自然映射",
    )
    product_name: str = Field(..., description="商品名称")
    product_description: Optional[str] = Field(None, description="商品描述/卖点综述，可为空")
    audience_pain_points: list[str] = Field(
        default_factory=list,
        description="受众痛点列表，可为空",
    )
    audience_demographics: dict[str, Any] = Field(
        default_factory=dict,
        description="受众人口画像（年龄/性别/动机等），可为空",
    )


# ---------------------------------------------------------------------------
# Product 抽取
# ---------------------------------------------------------------------------


class ProductExtractionResult(BaseModel):
    """``ProductExtractorAgent`` 输出契约。

    从商品页面/物料中抽取的结构化商品信息，供脚本生成与合规校验使用；
    ``category`` 字段值应与 ProductCategory 枚举（W1-T1 产出）保持一致。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="商品名称")
    brand: Optional[str] = Field(None, description="品牌名；缺失时为 None")
    category: str = Field(..., description="商品品类，应匹配 ProductCategory 枚举值")
    description: str = Field(..., description="商品描述/卖点综述")
    price_anchor: Optional[float] = Field(None, description="价格锚点；缺失时为 None")
    sku: Optional[str] = Field(None, description="SKU 标识；缺失时为 None")
    selling_points: list[str] = Field(
        ...,
        max_length=5,
        description="核心卖点列表，最多 5 条",
    )
    pain_points_solved: list[str] = Field(
        ...,
        max_length=5,
        description="该商品解决的用户痛点列表，最多 5 条",
    )
    target_audience: dict = Field(..., description="目标受众画像（人群/场景/动机等）")
    catchphrases: list[str] = Field(..., description="可复用的口号/金句列表")
    competitor_names: list[str] = Field(..., description="主要竞品名称列表")
    health_disclaimer_required: bool = Field(
        ...,
        description="是否需要附加健康类免责声明（食品/保健品/医美等品类需开启）",
    )


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


class ComplianceFinding(BaseModel):
    """单条合规校验发现项。

    描述一条违规命中（或建议）以及其严重程度、定位与建议修复方案，
    供 ``ComplianceCheckerAgent`` 聚合到 ``ComplianceReport``。
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., description="规则唯一标识")
    rule_kind: Literal[
        "banned_phrase",
        "required_label",
        "required_disclaimer",
        "brand_mention_cap",
    ] = Field(..., description="规则类型")
    severity: Literal["info", "warning", "blocker"] = Field(
        ...,
        description="严重程度：info / warning / blocker",
    )
    description: str = Field(..., description="问题描述")
    location: Optional[str] = Field(None, description="问题定位（镜头 ID/字段路径）")
    suggested_fix: Optional[str] = Field(None, description="建议修复方案；可为空")


class ComplianceReport(BaseModel):
    """``ComplianceCheckerAgent`` 输出契约。

    针对某地区与品类下的脚本聚合所有 ``ComplianceFinding``，
    并给出总体得分与摘要。``variant_id`` 在落库前预校验时为 None。
    """

    model_config = ConfigDict(extra="forbid")

    variant_id: Optional[str] = Field(
        None,
        description="脚本变体 ID；落库前预校验场景为 None",
    )
    region: str = Field(..., description="目标合规地区，如 CN / US")
    product_category: str = Field(..., description="商品品类，应匹配 ProductCategory 枚举值")
    findings: list[ComplianceFinding] = Field(..., description="合规问题清单")
    score: int = Field(..., ge=0, le=100, description="合规综合得分，区间 [0, 100]")
    summary: str = Field(..., description="合规校验摘要文本")


# ---------------------------------------------------------------------------
# 前向兼容（P2 ArchetypeVoiceRewriter）
# ---------------------------------------------------------------------------


# Used by P2 ArchetypeVoiceRewriter; included in P1 contracts for forward-compat
# — DO NOT use in P1 agents.
class BrandVoice(BaseModel):
    """品牌声音占位结构（P2 ArchetypeVoiceRewriter 使用）。

    P1 阶段不在任何 Agent 中使用，仅为后续阶段的 archetype + tone_grid
    重写器预留接口；保留在共享契约中以避免后续破坏性改动。
    """

    model_config = ConfigDict(extra="forbid")

    archetype: str = Field(..., description="品牌人格原型（占位）")
    tone_grid: dict = Field(..., description="调性网格占位结构")


# ---------------------------------------------------------------------------
# CTA 文案（W12-T2 CTAWriterAgent）
# ---------------------------------------------------------------------------


class CTAText(BaseModel):
    """结尾 CTA 输出 — CTAWriterAgent 的产出。

    描述一条结尾 Call-To-Action 文案的产出结果，包含文本本体、
    所采用的 cta_pattern ID、硬度等级、紧迫感类型以及（可选的）
    转化设计简要说明，供任务编排与素材落库消费。
    """

    model_config = ConfigDict(extra="forbid")

    cta_text: str = Field(
        ...,
        min_length=4,
        max_length=120,
        description="CTA 文本（中文，包含动作号召）",
    )
    pattern_id: str = Field(..., description="使用的 cta_pattern ID")
    hardness: str = Field(..., description="soft/medium/hard")
    urgency_type: str = Field(
        ...,
        description="scarcity/urgency/social_proof/benefit/risk_removal",
    )
    rationale: str | None = Field(None, description="转化设计简要说明")


class CTAWriteVars(BaseModel):
    """CTAWriterAgent 的输入变量。

    封装写作 CTA 所需的全部上下文：所选 cta_pattern、硬度、
    紧迫感类型、商品基本信息（名称/链接/折扣文案）以及目标动作，
    用于驱动 LLM 输出符合 CTAText schema 的结果。
    """

    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    hardness: str
    urgency_type: str
    product_name: str
    product_url: str | None = None
    discount_text: str | None = None
    target_action: str = Field(
        default="加购",
        description="目标动作：加购/下单/关注/查看/试用",
    )
