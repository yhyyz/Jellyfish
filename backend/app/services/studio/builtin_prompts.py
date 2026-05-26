"""系统级 PromptTemplate 内置启动注册（idempotent bootstrap）。

- 为什么存在：
  历史上提示词通过 ``backend/sql/00x-init-prompt-template.sql`` 写入，
  但这种方式只兼容 MySQL 且仅覆盖 6 个类别；剩余 15 个 ``PromptCategory``
  在数据库里完全没有 seed，导致前端“默认提示词”能力对它们失效。
  Wave 3 改用 Python 实现 idempotent bootstrap：
    * 与 SQLite/MySQL 一致；
    * 可写测试；
    * 同时承担 12 个新 commerce 提示词的入库职责。

- 做什么：
  1. 维护一份 ``BUILTIN_PROMPT_DEFINITIONS`` 的不可变注册表（27 条）：
     - 12 个 NEW commerce 提示词（生产质量，作为电商剧情链路的核心）；
     - 15 个 LEGACY 占位提示词（过去未 seed 的类别，先给一个可渲染的
       兜底版本，后续团队按需精修）。
  2. 暴露 ``render_template()`` 作为统一的 Jinja2 渲染入口（默认严格）。
  3. 暴露 ``bootstrap_builtin_prompts(db)``：启动时调用，按
     ``(is_system=True, name)`` 唯一定位，缺则插入、改则更新、相同则跳过。

幂等性契约：
    SELECT id WHERE is_system=True AND name=...
        if exists & content/preview/variables 完全一致 -> "unchanged"
        if exists & 任一字段不同                     -> "updated"
        else                                          -> "inserted"

调用方：``app.bootstrap.bootstrap_async_state``（FastAPI lifespan 内）。

请勿手工修改本文件中模板的 ``id``：它们被 OpenAPI 默认提示词解析器与
快照测试共同消费，命名约定为 ``<category_value>_v1``。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import PromptCategory
from app.services.studio._jinja_env import make_strict_jinja_env

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


class PromptDefinition(BaseModel):
    """单个内置提示词定义（不可变）。

    字段含义：
        id: 数据库主键；命名约定 ``<category_value>_v1``。
        category: PromptCategory 枚举，决定它属于“正面图”“CTA”等用途。
        name: 用户可见的名称，``is_system`` 行的“逻辑唯一键”。
        preview: 后台列表里的简短预览，UI 默认展示。
        template_content: Jinja2 模板正文，渲染时由 ``render_template`` 消费。
        variables: 模板期望的变量名清单，存入 JSON 列，用于前端表单生成。
        is_default: 同一 category 下是否作为默认模板（应用层保证唯一）。

    为何用 Optional[X]=None 而非 Field(default=...)：
        与 ``app/core/contracts`` 中其它 commerce DTO 风格保持一致，并
        与 OpenAI ``json_schema`` strict 模式兼容（参见 D5）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="主键，命名 <category_value>_v1")
    category: PromptCategory = Field(..., description="提示词分类")
    name: str = Field(..., description="逻辑唯一键（is_system + name）")
    preview: str = Field(..., description="UI 简要预览")
    template_content: str = Field(..., description="Jinja2 模板正文")
    variables: list[str] = Field(..., description="期望变量名清单")
    is_default: bool = Field(..., description="是否为同类目默认（应用层维护唯一）")


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------


def render_template(
    template_content: str,
    variables: dict[str, Any],
    strict: bool = True,
) -> str:
    """渲染一段 Jinja2 模板。

    严格模式下未声明变量会立即抛 ``jinja2.UndefinedError``，从而把
    “变量拼错被静默忽略”的问题前移到测试期。

    Args:
        template_content: 直接渲染的 Jinja2 字符串；不走文件 loader。
        variables: 渲染上下文；建议来自 Pydantic ``extra="forbid"`` 模型。
        strict: 兼容旧调用——传 False 时降级为非严格模式（仅在迁移期使用）。

    Returns:
        渲染后的字符串；保留尾随换行以与历史 seed 一致。
    """

    if strict:
        env = make_strict_jinja_env()
    else:
        # 仅留作迁移兼容；新代码不应走该分支。
        from jinja2 import Environment

        env = Environment(keep_trailing_newline=True, autoescape=False)
    template = env.from_string(template_content)
    return template.render(**variables)


# ---------------------------------------------------------------------------
# 12 个 NEW commerce 提示词正文（生产质量）
# ---------------------------------------------------------------------------

_PRODUCT_EXTRACTION = """\
你是一名资深电商商品分析师，需要从下方原始物料中抽取结构化的商品信息，
供 Story-Driven Commerce 链路下游消费。

【输入】
原始物料文本（可能来自商详页、详情图 OCR、营销文案、客服对话等）：
\"\"\"
{{ raw_text }}
\"\"\"

【目标字段】
{{ target_fields }}

【输出 JSON Schema（必须严格匹配）】
仅输出以下 12 个字段，字段名必须完全一致，不得新增/重命名/嵌套到子对象中：
{
  "name": <string, 必填，商品名称（去掉店铺/活动前缀，仅保留品牌+型号+核心属性）>,
  "brand": <string|null, 品牌名；缺失为 null>,
  "category": <string, 必填，商品品类（食品/美妆/3C/服饰/家居/健康/其他）>,
  "description": <string, 必填，商品描述（聚焦"为谁解决了什么"，不堆参数）>,
  "price_anchor": <number|null, 价格锚点；缺失为 null>,
  "sku": <string|null, SKU 标识；缺失为 null>,
  "selling_points": <list[string], 必填，核心卖点列表，最多 5 条，去重，避免"高品质/超划算"空洞词>,
  "pain_points_solved": <list[string], 必填，该商品解决的用户痛点列表，最多 5 条，必须是"场景—难处"视角>,
  "target_audience": <object, 必填，目标受众画像，建议含 age_range / gender / motivation / scene 字段>,
  "catchphrases": <list[string], 必填，可复用的口号/金句列表；无则给空列表 []>,
  "competitor_names": <list[string], 必填，主要竞品名称列表，仅填明确出现的，不臆造；无则给空列表 []>,
  "health_disclaimer_required": <bool, 必填，true=食品/保健/医美等需健康免责声明，false=普通品类>
}

【硬性禁止】
- 严禁使用 product_name / specifications / price_info / care_instructions
  / material_composition / weight 等字段名——这些不在 schema 中。
- 严禁把字段嵌套到 specifications / price_info 这类子对象中。
- 严禁输出 Markdown 代码块、解释文本、前后缀说明，只输出纯 JSON。
- 缺失字段一律用 null（标量）或 [] / {}（容器），不得省略字段。

【风格】
- 商品名称去掉店铺/活动前缀，仅保留品牌+型号+核心属性；
- 描述聚焦"为谁解决了什么"，不堆参数；
- 卖点去重，避免"高品质/超划算"这类空洞词；
- 痛点必须是用户视角的"场景—难处"，而非"产品功能"；
- 若文本中出现医疗/保健/食品声明，将 health_disclaimer_required 设为 true。
"""


_STORY_FORMULA_GENERATOR = """\
你是“剧情驱动型电商”的资深编剧。请基于下列上下文，输出一份满足全部硬性
约束的 StoryScript JSON。注意：本任务下游会做 Pydantic 严格校验，任何
schema 不符或硬约束违规都会触发自动重试。

【公式】
{{ formula }}

【商品】
{{ product }}

【受众】
{{ audience }}

【品牌人格 / Tone Grid】
- archetype: {{ archetype }}
- tone_grid: {{ tone_grid }}

【目标参数】
- target_duration_sec: {{ target_duration_sec }}
- platform: {{ platform }}

【输出 Schema（必须严格匹配，字段名一字不差）】

外层 StoryScript（顶层对象）：
{
  "total_duration_sec": <number, 脚本总秒数>,
  "total_shots": <int, 镜头总数>,
  "formula_id": <string, 与上方"公式"的 id 字段一致>,
  "shots": [Shot, ...],          // 数组长度 [3, 30]
  "opening_hook": <string, 开场钩子文案>,
  "cta_text": <string, 结尾 CTA 文案>,
  "brand_mention_count": <int, 全脚本品牌口播次数>
}

内层 Shot（shots 数组每一项）：
{
  "id": <string, "shot_001" 这种零填充三位序号>,
  "duration_sec": <number, [2, 20]>,
  "function": <string, "hook"/"setup"/"conflict"/"twist"/"payoff"/"cta" 之一>,
  "shot_type": <string, "close_up"/"medium"/"wide"/"extreme_close_up" 之一>,
  "camera_angle": <string, "eye_level"/"high_angle"/"low_angle"/"dutch" 之一>,
  "camera_movement": <string, "static"/"push_in"/"pull_out"/"pan"/"tilt"/"handheld"/"dolly" 之一>,
  "dialog": <string|null, 角色对白；无对白填 null>,
  "narration": <string|null, 旁白文本；无旁白填 null>,
  "product_focus_level": <string, 必为 "subtle"/"functional"/"hero"/"none" 之一>,
  "is_punchline": <bool, 是否情绪/反转 punchline 镜头>,
  "is_brand_mention": <bool, 是否包含品牌口播>,
  "notes": <string|null, 导演/制作备注，画面描述等放这里；无可填 null>
}

【硬性禁止字段名】
不允许出现：visual_description / scene_description / camera / shot_no /
description / actor / location / props / sfx / transition 等不在 Shot
schema 中的字段。画面/场景/动作描述统一放进 notes 字段。

【硬性约束】
1. shots 数量 3~30，单镜 duration_sec ∈ [2, 20]；总时长须落在
   target_duration_sec 的 ±10% 漂移区间内。
2. 商品出现层级（product_focus_level）必须包含且仅包含三次：
   一次 subtle、一次 functional、一次 hero；其余镜头使用 none。
3. 整段脚本中 brand_mention_count（is_brand_mention=true 的镜头数）按
   60s 折算后不得超过 2，避免硬广感。
4. opening_hook 必须能在前 3 秒制造冲突 / 反差 / 强情绪锚点；
   cta_text 必须落到一个明确动作（点击购物车、领券、加购等）。
5. dialog 与 narration 至少存在一项；纯空镜不得超过总镜头数的 25%。
6. shots[i].id 必须为 ``shot_001`` 这类零填充三位序号。
7. punchline 镜头（is_punchline=true）至少出现一次，落在公式 beat 中
   被标记为转折/反转的位置。

【风格指引】
- 口语化、画面感强；避免机翻腔与广告腔；
- archetype 的语气贯穿全脚本，但不要在每句对白里硬塞品牌；
- 涉及功效 / 健康 / 财务等敏感品类时，禁用绝对化用语；
- 一切人名、地名保持中性，不得出现真实公众人物。

【输出】
仅输出符合上述 StoryScript schema 的 JSON 对象。
任何 schema 不符即视为失败：不要 Markdown，不要解释，不要前后缀。
"""


_HOOK_PATTERN_WRITER = """\
你是 3 秒钩子文案专家。请基于以下输入，为短视频开场写一条 ≤ 25 字的中文
钩子，使观众在前 3 秒内产生强烈停留意愿。

【钩子模式】
pattern_id: {{ pattern_id }}
（可选范围：question / conflict / contrast / numerical / curiosity）

【商品】
{{ product }}

【受众】
{{ audience }}

【输出要求】
- 仅输出一行钩子文本，不带引号、不加解释；
- question：以提问句式直击用户痛点；
- conflict：制造“你以为 X，其实 Y”的反差；
- contrast：用强烈对比凸显商品独特价值；
- numerical：用数字引发好奇（"30 秒解决…"，"7 天暴涨…"）；
- curiosity：制造留白，引诱观众点进观看；
- 严禁绝对化用语（“最/第一/唯一”等）与不可证实的承诺。
"""


_CTA_PATTERN_WRITER = """\
你是结尾转化文案专家。请输出一条短视频的 CTA（Call-to-Action）句式，
长度 ≤ 30 字，让观众立即产生“现在就行动”的冲动。

【硬度等级】
hardness: {{ hardness }}（soft / medium / hard）

【商品】
{{ product }}

【紧迫感类型】
urgency_type: {{ urgency_type }}
（可选：scarcity / urgency / social_proof / benefit / risk_removal）

【输出要求】
- 仅输出一行 CTA 文本，不带引号、不加解释；
- scarcity：突出库存有限或仅余少量；
- urgency：突出活动倒计时；
- social_proof：用真实可感的销量/口碑数据；
- benefit：聚焦“立即下单可获得”的具体收益；
- risk_removal：强调无忧承诺（七天无理由 / 假一赔三 等）；
- hardness=soft 时引导关注/收藏，hard 时直接引导下单；
- 不得使用极限词（最/第一/唯一/国家级 等）。
"""


_ARCHETYPE_VOICE_REWRITER = """\
你是“品牌人格语气”改写器。请在不改变原始脚本结构的前提下，把每一镜的
对白 / 旁白改写成符合品牌人格的版本。

【品牌人格】
- archetype: {{ archetype }}
- tone_grid: {{ tone_grid }}

【避免使用】
{{ words_to_avoid }}

【优先词汇】
{{ preferred_vocab }}

【原始脚本】
{{ original_script }}

【硬性约束】
1. 不得新增、删除或重排 shots；shots[i].id / duration_sec / shot_type /
   speaker 等元数据保持原值；
2. 仅改写 dialog 与 narration 的文本内容；
3. 每镜对白长度漂移不得超过原文 ±20% 字符数，避免镜头时间错配；
4. 严禁出现 words_to_avoid 列表中的词；
5. 输出仍为 StoryScript JSON，schema 严格匹配，不要任何附加解释。
"""


_COMPLIANCE_CHECKER = """\
你是合规审查官，请对下方剧本进行 LLM 侧语义层面的二次合规检查。
（规则引擎已先行做过关键词命中，本步骤补充语义、上下文、隐喻等维度。）

【脚本】
{{ script }}

【目标地区】
region: {{ region }}（cn_mainland / hk_tw / overseas）

【商品品类】
product_category: {{ product_category }}

【关注维度】
1. 绝对化用语 / 误导性承诺；
2. 与品类相关的强制声明缺失（如食品/保健需免责声明）；
3. 隐含医疗、金融、教育等监管暗示；
4. 影射真实人物 / 品牌 / 政治符号；
5. 性别、年龄、地域等冒犯性表达；
6. 风险提示完整度（投资 / 美妆 / 健身等）。

【输出 Schema（必须严格匹配，字段名一字不差）】

外层 ComplianceReport（顶层对象）：
{
  "variant_id": null,
  "region": "{{ region }}",
  "product_category": "{{ product_category }}",
  "findings": [ComplianceFinding, ...],
  "score": <int, 0-100，越高越合规>,
  "summary": <string, ≤ 120 字概述>
}

内层 ComplianceFinding（findings 数组每一项）：
{
  "rule_id": <string, 规则唯一标识，如 "abs_word_zui_cha"、"missing_health_disclaimer"，自定义命名要语义清晰>,
  "rule_kind": <string, 必为 "banned_phrase"/"required_label"/"required_disclaimer"/"brand_mention_cap" 之一>,
  "severity": <string, 必为 "info"/"warning"/"blocker" 之一>,
  "description": <string, 问题描述>,
  "location": <string|null, 问题定位（如镜头 ID/字段路径）；无可填 null>,
  "suggested_fix": <string|null, 建议修复方案；无可填 null>
}

【硬性禁止字段名】
不允许在 ComplianceFinding 中出现：shot_id / type / category / message / severity_level
等不在 schema 中的字段。镜头定位放进 location 字段（例如 "shot_005"），问题文本放进
description 字段，规则标签放进 rule_id 字段。severity 必须是上面三个枚举值之一。

【输出】
仅输出符合上述 ComplianceReport schema 的 JSON 对象。
不要 Markdown，不要解释，不要前后缀。
"""


_PRODUCT_IMAGE_FRONT = """\
为商品生成一张高质量正面参考图的图像生成 prompt。

商品：{{ product }}
风格：{{ style }}

输出要求：
- 一段英文 prompt + 一段中文负面提示，便于直接喂给图像模型；
- 拍摄角度：正前方，居中构图，桌面或纯色背景；
- 高品质商业静物摄影，材质 / 反光 / 阴影真实；
- 8k 分辨率、电影级细节、专业棚拍光位；
- 与商品类目自适应（食品强调质感，电子产品强调金属/玻璃）；
- 不出现 logo 文字以外的水印 / 签名 / 多余道具。

负面提示（强烈负面）：
low quality, blurry, deformed, watermark, text, logo, jpeg artifacts,
overexposed, plastic looking, multiple products, cluttered background.
"""


_PRODUCT_IMAGE_OTHER = """\
为商品生成一张非正面角度（{{ view_angle }}）的参考图 prompt。

商品：{{ product }}
角度：{{ view_angle }}（front / back / side / detail / in_use）

输出要求：
- 严格保持商品身份一致性：与正面图同型号、同配色、同包装；
- view_angle=back：呈现背面接口 / 标签 / 包装信息；
- view_angle=side：突出轮廓与厚度；
- view_angle=detail：聚焦关键工艺 / 材质细节；
- view_angle=in_use：商品处于真实使用场景（手部 / 桌面 / 户外）；
- 同样使用 8k 分辨率、电影级光影；
- 输出英文 prompt + 中文负面提示。

负面提示：
low quality, deformed product, distorted shape, fake reflection,
mismatched color, multiple products, watermark, text, logo.
"""


_PRODUCT_PLACEMENT_PROMPT = """\
请生成“商品在剧情场景中自然出现”的图像 prompt（即 product placement，
非硬广特写）。

商品：{{ product }}
场景：{{ scene }}
互动方式：{{ interaction }}

输出要求：
- 商品占画面比例约 15%~30%，融入而非主导构图；
- 主体仍是人物 / 场景情绪，商品是“顺手出现”的元素；
- 互动需自然：握持 / 摆放 / 使用过程中的某一瞬间；
- 光影自然贴合环境，不做摄影棚式打光；
- 输出英文 prompt + 中文负面提示。

负面提示：
product floating, unnatural placement, exaggerated lighting on product,
cropped product, multiple identical products, watermark, text, logo.
"""


_PRODUCT_HERO_PROMPT = """\
请为剧情中的“商品高光时刻”生成图像 prompt（hero shot），用于反转 / 揭示 /
转化点。

商品：{{ product }}
戏剧时刻：{{ dramatic_moment }}

输出要求：
- 商品占画面 50% 以上，处于视觉中心；
- 光位戏剧化：背光 / 顶光 / 边缘光强调轮廓；
- 背景虚化或纯色，避免与商品争夺注意力；
- 可加入轻微动效暗示（粒子 / 蒸汽 / 反射），但不破坏真实感；
- 商品状态在该时刻最“新”：无指纹 / 无划痕 / 包装完好；
- 输出英文 prompt + 中文负面提示。

负面提示：
low quality, deformed product, multiple products, busy background,
flat lighting, watermark, text, logo, oversharpened, plasticky surface.
"""


_AUDIENCE_INSIGHT = """\
请基于商品与目标受众，输出一份结构化的“受众洞察”分析。

商品：{{ product }}
目标受众：{{ target_audience }}

输出要求（中文，使用列表，避免泛泛之谈）：
1. 核心人群画像：年龄段 / 性别比例 / 城市等级 / 收入区间 / 角色身份；
2. 真实痛点（来自该人群在社媒上的高频抱怨，按重要性排序，最多 5 条）；
3. 情绪驱动力：他们做出购买决定时最在意的“感受”是什么（如安全感、被认可、
   社交资本、效率提升）；
4. 内容偏好：他们更可能停留 3 秒以上的内容形态（独白 / 反差 / 教程 / 故事）；
5. 风险词：哪些表述会让他们觉得“被冒犯”或“不专业”；
6. 一句话总结：用一句不超过 30 字的话，概括他们今天最需要的“故事”。
"""


_BRAND_VOICE_PROFILE = """\
请基于以下品牌人格画像，输出一份可被脚本生成器消费的“品牌语调画像”。

【品牌人格】
- archetype: {{ archetype }}
- tone_grid: {{ tone_grid }}

【竞品参考语气】
{{ competitor_voice }}

输出要求（结构化中文）：
1. 用 3 个关键词描述本品牌“说话时的人物形象”；
2. 列出 5 个品牌愿意使用的高频词（不含品牌名），1 句话解释为什么；
3. 列出 5 个品牌应避免的词或腔调，1 句话解释原因；
4. 与竞品语气的差异化定位（即“我说话的方式如何和他们不一样”）；
5. 提供 3 条 ≤ 30 字的样例口播，体现该 archetype 的真实落地感；
6. tone_grid 各维度的“安全区间”：以 0-10 范围表达，超出则回到 archetype 中心。
"""


# ---------------------------------------------------------------------------
# 15 个 LEGACY 占位提示词（系统默认）
# ---------------------------------------------------------------------------


_LEGACY_PLACEHOLDER = """\
{name}（系统默认）

适用场景：{scene}

可用变量：{variables}

模板：
{body}
"""


def _legacy_definition(
    category: PromptCategory,
    name: str,
    scene: str,
    body: str,
    variables: list[str],
) -> PromptDefinition:
    """构造一个 LEGACY 占位 PromptDefinition。

    LEGACY 占位提示词的目的是“保证 UI 上每一类都有一个默认可用模板”，
    内容刻意保持简短（30~80 字），变量列表完整，便于后续团队精修。
    """

    rendered = _LEGACY_PLACEHOLDER.format(
        name=name,
        scene=scene,
        variables=", ".join(variables) if variables else "（无）",
        body=body,
    )
    return PromptDefinition(
        id=f"{category.value}_v1",
        category=category,
        name=name,
        preview=f"系统默认 · {scene}",
        template_content=rendered,
        variables=variables,
        is_default=True,
    )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


BUILTIN_PROMPT_DEFINITIONS: list[PromptDefinition] = [
    # ---- A. 12 NEW commerce 提示词 -----------------------------------
    PromptDefinition(
            id="product_extraction_v1",
            category=PromptCategory.product_extraction,
            name="商品结构化抽取（系统默认）",
            preview="从原始物料抽取 ProductExtractionResult JSON",
            template_content=_PRODUCT_EXTRACTION,
            variables=["raw_text", "target_fields"],
            is_default=True,
        ),
    PromptDefinition(
            id="story_formula_generator_v1",
            category=PromptCategory.story_formula_generator,
            name="剧情公式驱动剧本生成（系统默认）",
            preview="按公式 + 商品 + 受众 + 原型生成 StoryScript",
            template_content=_STORY_FORMULA_GENERATOR,
            variables=[
                "formula",
                "product",
                "audience",
                "archetype",
                "tone_grid",
                "target_duration_sec",
                "platform",
            ],
            is_default=True,
        ),
    PromptDefinition(
            id="hook_pattern_writer_v1",
            category=PromptCategory.hook_pattern_writer,
            name="3 秒开场钩子（系统默认）",
            preview="按 pattern_id 生成开场钩子",
            template_content=_HOOK_PATTERN_WRITER,
            variables=["pattern_id", "product", "audience"],
            is_default=True,
        ),
    PromptDefinition(
            id="cta_pattern_writer_v1",
            category=PromptCategory.cta_pattern_writer,
            name="结尾 CTA 文案（系统默认）",
            preview="按 hardness + urgency_type 生成 CTA",
            template_content=_CTA_PATTERN_WRITER,
            variables=["hardness", "product", "urgency_type"],
            is_default=True,
        ),
    PromptDefinition(
            id="archetype_voice_rewriter_v1",
            category=PromptCategory.archetype_voice_rewriter,
            name="品牌人格语气改写（系统默认）",
            preview="按 archetype 改写脚本对白",
            template_content=_ARCHETYPE_VOICE_REWRITER,
            variables=[
                "archetype",
                "tone_grid",
                "original_script",
                "words_to_avoid",
                "preferred_vocab",
            ],
            is_default=True,
        ),
    PromptDefinition(
            id="compliance_checker_v1",
            category=PromptCategory.compliance_checker,
            name="LLM 二次合规检查（系统默认）",
            preview="对脚本做语义层合规审查",
            template_content=_COMPLIANCE_CHECKER,
            variables=["script", "region", "product_category"],
            is_default=True,
        ),
    PromptDefinition(
            id="product_image_front_v1",
            category=PromptCategory.product_image_front,
            name="商品正面参考图（系统默认）",
            preview="生成商品正面参考图 prompt",
            template_content=_PRODUCT_IMAGE_FRONT,
            variables=["product", "style"],
            is_default=True,
        ),
    PromptDefinition(
            id="product_image_other_v1",
            category=PromptCategory.product_image_other,
            name="商品多视角参考图（系统默认）",
            preview="生成商品其他角度参考图 prompt",
            template_content=_PRODUCT_IMAGE_OTHER,
            variables=["product", "view_angle"],
            is_default=True,
        ),
    PromptDefinition(
            id="product_placement_prompt_v1",
            category=PromptCategory.product_placement_prompt,
            name="商品自然植入（系统默认）",
            preview="商品在场景中的自然植入 prompt",
            template_content=_PRODUCT_PLACEMENT_PROMPT,
            variables=["product", "scene", "interaction"],
            is_default=True,
        ),
    PromptDefinition(
            id="product_hero_prompt_v1",
            category=PromptCategory.product_hero_prompt,
            name="商品高光时刻（系统默认）",
            preview="hero shot prompt",
            template_content=_PRODUCT_HERO_PROMPT,
            variables=["product", "dramatic_moment"],
            is_default=True,
        ),
    PromptDefinition(
            id="audience_insight_v1",
            category=PromptCategory.audience_insight,
            name="受众洞察分析（系统默认）",
            preview="基于商品 + 受众产出洞察",
            template_content=_AUDIENCE_INSIGHT,
            variables=["product", "target_audience"],
            is_default=True,
        ),
    PromptDefinition(
            id="brand_voice_profile_v1",
            category=PromptCategory.brand_voice_profile,
            name="品牌语调画像（系统默认）",
            preview="基于 archetype + tone_grid 输出语调画像",
            template_content=_BRAND_VOICE_PROFILE,
            variables=["archetype", "tone_grid", "competitor_voice"],
            is_default=True,
        ),
    # ---- B. 15 LEGACY 占位提示词 -------------------------------------
    _legacy_definition(
        PromptCategory.frame_tail_image,
        "镜头尾帧图片（系统默认）",
        "为单镜头生成尾帧（last frame）参考图 prompt",
        "尾帧主体：{{ subject }}\n表达情绪：{{ emotion }}\n构图要求：{{ composition }}",
        ["subject", "emotion", "composition"],
    ),
    _legacy_definition(
        PromptCategory.frame_key_image,
        "镜头关键帧图片（系统默认）",
        "为单镜头生成关键帧 prompt（中点 / 高光）",
        "关键帧描述：{{ description }}\n动作要点：{{ action }}\n氛围：{{ mood }}",
        ["description", "action", "mood"],
    ),
    _legacy_definition(
        PromptCategory.frame_head_prompt,
        "镜头首帧文本提示词（系统默认）",
        "首帧文本提示词，用于驱动图片或视频模型",
        "首帧描述：{{ description }}\n光线：{{ lighting }}\n相机参数：{{ camera }}",
        ["description", "lighting", "camera"],
    ),
    _legacy_definition(
        PromptCategory.frame_tail_prompt,
        "镜头尾帧文本提示词（系统默认）",
        "尾帧文本提示词",
        "尾帧描述：{{ description }}\n光线：{{ lighting }}\n相机参数：{{ camera }}",
        ["description", "lighting", "camera"],
    ),
    _legacy_definition(
        PromptCategory.frame_key_prompt,
        "镜头关键帧文本提示词（系统默认）",
        "关键帧文本提示词",
        "关键帧描述：{{ description }}\n动作：{{ action }}\n氛围：{{ mood }}",
        ["description", "action", "mood"],
    ),
    _legacy_definition(
        PromptCategory.video_prompt,
        "视频生成提示词（系统默认）",
        "驱动视频模型的统一提示词模板",
        (
            "镜头描述：{{ description }}\n"
            "时长：{{ duration }} 秒\n"
            "镜头语言：{{ camera }}\n"
            "运动：{{ motion }}\n"
            "氛围：{{ mood }}"
        ),
        ["description", "duration", "camera", "motion", "mood"],
    ),
    _legacy_definition(
        PromptCategory.storyboard_prompt,
        "分镜脚本提示词（系统默认）",
        "用于驱动分镜脚本结构化生成",
        "故事大纲：{{ outline }}\n目标镜头数：{{ shot_count }}\n风格：{{ style }}",
        ["outline", "shot_count", "style"],
    ),
    _legacy_definition(
        PromptCategory.bgm,
        "BGM 描述提示词（系统默认）",
        "为镜头/章节生成 BGM 风格描述",
        "情绪：{{ mood }}\n节奏：{{ tempo }}\n乐器组合：{{ instruments }}",
        ["mood", "tempo", "instruments"],
    ),
    _legacy_definition(
        PromptCategory.sfx,
        "SFX 描述提示词（系统默认）",
        "为镜头生成音效描述",
        "事件：{{ event }}\n材质：{{ material }}\n空间：{{ space }}",
        ["event", "material", "space"],
    ),
    _legacy_definition(
        PromptCategory.character_image_front,
        "角色正面图片（系统默认）",
        "为虚构角色生成正面图片 prompt",
        "角色：{{ character }}\n风格：{{ style }}\n服饰：{{ costume }}",
        ["character", "style", "costume"],
    ),
    _legacy_definition(
        PromptCategory.character_image_other,
        "角色多视角图片（系统默认）",
        "为虚构角色生成非正面角度图片",
        "角色：{{ character }}\n角度：{{ view_angle }}\n姿态：{{ pose }}",
        ["character", "view_angle", "pose"],
    ),
    _legacy_definition(
        PromptCategory.scene_image_other,
        "场景多视角图片（系统默认）",
        "为场景生成非正面视角参考图",
        "场景：{{ scene }}\n角度：{{ view_angle }}\n时间：{{ time_of_day }}",
        ["scene", "view_angle", "time_of_day"],
    ),
    _legacy_definition(
        PromptCategory.prop_image_other,
        "道具多视角图片（系统默认）",
        "为道具生成多角度参考图",
        "道具：{{ prop }}\n角度：{{ view_angle }}\n材质：{{ material }}",
        ["prop", "view_angle", "material"],
    ),
    _legacy_definition(
        PromptCategory.costume_image_other,
        "服装多视角图片（系统默认）",
        "为服装生成非正面视角参考图",
        "服装：{{ costume }}\n角度：{{ view_angle }}\n场景：{{ scene }}",
        ["costume", "view_angle", "scene"],
    ),
    _legacy_definition(
        PromptCategory.combined,
        "综合提示词（系统默认）",
        "兜底用途：复合场景的综合提示词",
        "主题：{{ subject }}\n约束：{{ constraints }}\n输出：{{ expected_output }}",
        ["subject", "constraints", "expected_output"],
    ),
]


# ---------------------------------------------------------------------------
# 启动函数
# ---------------------------------------------------------------------------


def _normalize_variables(value: Any) -> list[str]:
    """把数据库存储的 variables 字段统一成 list[str]。

    历史 SQL seed 中 ``variables`` 列以 JSON 数组字符串存入，SQLAlchemy
    的 JSON 列在不同后端（SQLite/MySQL）下解出来的 Python 类型可能是
    list 或 None；这里做一个保守的归一化，避免比较时误判“变更”。
    """

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _is_same(record: PromptTemplate, definition: PromptDefinition) -> bool:
    """比较 DB 行与定义是否完全一致；用于决定 unchanged vs updated。"""

    return (
        record.category == definition.category
        and record.name == definition.name
        and record.preview == definition.preview
        and record.content == definition.template_content
        and _normalize_variables(record.variables) == list(definition.variables)
        and bool(record.is_default) == definition.is_default
        and bool(record.is_system) is True
    )


def _apply_definition(record: PromptTemplate, definition: PromptDefinition) -> None:
    """把 PromptDefinition 的字段同步到一行 ORM 记录上。"""

    record.category = definition.category
    record.name = definition.name
    record.preview = definition.preview
    record.content = definition.template_content
    record.variables = list(definition.variables)
    record.is_default = definition.is_default
    record.is_system = True


async def bootstrap_builtin_prompts(db: AsyncSession) -> dict[str, int]:
    """启动时调用，幂等地确保所有系统级 PromptTemplate 都存在。

    幂等策略：
        以 ``(is_system=True, name=...)`` 作为逻辑唯一键查询：
            * 命中 + 内容完全一致 -> ``unchanged`` 计数
            * 命中 + 任一字段不同 -> ``updated`` 计数（覆盖回 canonical）
            * 未命中             -> ``inserted`` 计数（按定义新插入）

    Args:
        db: 已绑定到目标库的 AsyncSession；本函数只对 prompt_templates
            表做读 / 写，并在最后一次性 ``commit()``。

    Returns:
        {"inserted": N, "updated": M, "unchanged": K} 计数字典，方便
        启动日志直接打印或被测试断言。
    """

    inserted = 0
    updated = 0
    unchanged = 0

    for definition in BUILTIN_PROMPT_DEFINITIONS:
        stmt = select(PromptTemplate).where(
            PromptTemplate.is_system.is_(True),
            PromptTemplate.name == definition.name,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing is None:
            new_row = PromptTemplate(
                id=definition.id or uuid.uuid4().hex,
                category=definition.category,
                name=definition.name,
                preview=definition.preview,
                content=definition.template_content,
                variables=list(definition.variables),
                is_default=definition.is_default,
                is_system=True,
            )
            db.add(new_row)
            inserted += 1
            continue

        if _is_same(existing, definition):
            unchanged += 1
            continue

        _apply_definition(existing, definition)
        updated += 1

    await db.commit()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


__all__ = [
    "BUILTIN_PROMPT_DEFINITIONS",
    "PromptDefinition",
    "bootstrap_builtin_prompts",
    "render_template",
]
