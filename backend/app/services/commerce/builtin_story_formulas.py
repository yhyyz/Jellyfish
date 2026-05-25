"""系统级剧情公式（StoryFormula）种子数据加载器（W3-T2 启 P1，W11-T1 起扩 P2）。

本模块提供两个东西：

1. ``BUILTIN_FORMULA_DEFINITIONS``：一个类型化、可在测试与 UI 复用的 12 条
   公式注册表，由两组组成：

   - **6 条中国市场爆款公式**（``region=cn``）：``underdog_triumph`` /
     ``contrast_surprise`` / ``workplace_hero`` / ``family_conflict`` /
     ``mystery_twist`` / ``time_travel``。
   - **6 条国际经典叙事公式**（``region=global_``）：``heros_journey`` /
     ``pixar_story_spine`` / ``three_act`` / ``scqa`` / ``storybrand_sb7`` /
     ``pas_bab``。

2. ``bootstrap_builtin_story_formulas(db)``：启动时调用的幂等加载函数，
   把上述定义同步到 ``story_formulas`` 表（INSERT-OR-UPDATE，
   ``is_system=True``）。

设计原则与边界：

- 公式数据是“运营/产品级别”的策划资产，因此放在 ``services/commerce``
  下作为可被 service 层、API 层、测试共同消费的“常量+加载器”，避免与
  ``app/core/contracts``（跨层 DTO）混淆。
- ``prompt_template_id`` 全部硬绑定到
  ``commerce_story_formula_generator_v1``（W3-T1 负责创建该模板）。
  运行时合同：``bootstrap_builtin_prompts`` 必须先于本函数执行，否则
  ``story_formulas.prompt_template_id`` 上的外键 ``ON DELETE RESTRICT``
  会拒绝插入。
- 所有合规风险标记（``risk_flags``）使用 :data:`KNOWN_RISK_FLAGS` 中
  约定的稳定词汇表，禁止自由发挥；新增风险类型必须扩 vocabulary 并
  同步到合规检查器（W4 阶段）与文档。

为什么单独引入 ``FormulaDefinition``：

- 直接维护 dict 列表会缺失类型校验，``risk_flags`` / ``beats`` 内部结构
  在 review 时极易写错；
- 用 Pydantic v2 ``BaseModel`` + ``ConfigDict(extra="forbid")`` 把 6 条
  公式当成“结构化配置”治理，能在测试与启动时第一时间拦截字段拼写
  错误，避免错误数据被写入数据库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryFormula
from app.models.types import FormulaRegion


# ---------------------------------------------------------------------------
# 风险标记词汇表（与合规检查器、运营文档共享）
# ---------------------------------------------------------------------------

#: 全量已知的风险标记，公式 ``risk_flags`` 必须是此集合的子集。
#: 任何扩展必须同步到合规检查器与文档（``site/content/docs/architecture``）。
KNOWN_RISK_FLAGS: frozenset[str] = frozenset(
    {
        # 必须在画面上显著标注 “演绎/虚构” 字样（中国短视频平台合规）。
        "requires_yanyi_label",
        # 含家庭冲突，需确保不出现婆媳互骂/亲子控诉式画面，否则限流/封号。
        "family_conflict_compliance",
        # 阶层/收入差距叙事，需避免对原雇主/家庭/母校的丑化。
        "class_sensitivity",
        # 易触发隐性健康功效宣称，需配合健康类合规（食药/医械免责）。
        "health_claim_risk",
        # 涉及性别角色/性别对立，需检查文案与镜头是否冒犯/极化。
        "gender_sensitivity",
        # 含 “你也能…/你将会…” 等无法验证的承诺，需软化与免责。
        "unverifiable_outcome",
    }
)


#: 所有内置公式统一绑定的提示词模板 ID。
#: 与 W3-T1 在 ``app/services/studio/builtin_prompts.py`` 中创建的
#: ``story_formula_generator_v1`` 模板严格对齐（命名约定：
#: ``<PromptCategory.value>_v1``，对应 ``story_formula_generator``）。
BUILTIN_FORMULA_PROMPT_TEMPLATE_ID = "story_formula_generator_v1"


# ---------------------------------------------------------------------------
# 数据契约：Beat / FormulaDefinition
# ---------------------------------------------------------------------------


class Beat(BaseModel):
    """单个叙事节拍（beat）的结构化定义。

    每个 beat 描述一段镜头组：
    - ``id``：节拍唯一名（snake_case），LLM 生成阶段会引用以保证可追溯。
    - ``duration_sec``：本节拍占用秒数；同一公式内全部节拍之和应≈
      ``typical_duration_sec``。
    - ``function``：本节拍承担的叙事功能（“为什么需要它”），影响 LLM 生
      成时的镜头意图。
    - ``shot_type``：建议景别（``close_up`` / ``medium_shot`` / ``wide_shot``
      / ``hand_object_face`` 等）。
    - ``recommended_camera_movement``：建议运镜，可为 ``None`` 表示静态。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    duration_sec: int = Field(..., ge=1, le=600)
    function: str = Field(..., min_length=1)
    shot_type: str = Field(..., min_length=1)
    recommended_camera_movement: str | None = None


class FormulaDefinition(BaseModel):
    """单条系统级公式定义。

    字段语义与 :class:`app.models.story_formula.StoryFormula` 严格对齐，
    便于一一映射；额外多出的 ``beats``/``total_shots_range``/
    ``duration_sec_range`` 通过 :meth:`to_structure_payload` 序列化进
    ``StoryFormula.structure`` JSON 列。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    region: FormulaRegion
    category: str = Field(..., min_length=1, max_length=64)
    beats: list[Beat] = Field(..., min_length=1)
    total_shots_range: tuple[int, int]
    duration_sec_range: tuple[int, int]
    risk_flags: list[str] = Field(default_factory=list)
    sample_dialog: str = Field(..., min_length=1)
    typical_duration_sec: int = Field(..., ge=10, le=600)
    typical_shot_count: int = Field(..., ge=1, le=20)
    psychology: str = Field(..., min_length=1)
    use_cases: list[str] = Field(..., min_length=1)
    avoid_cases: list[str] = Field(..., min_length=1)
    prompt_template_id: str = Field(default=BUILTIN_FORMULA_PROMPT_TEMPLATE_ID)
    is_system: bool = True
    sort_order: int = Field(..., ge=0)

    @field_validator("risk_flags")
    @classmethod
    def _validate_risk_flags(cls, value: list[str]) -> list[str]:
        """约束 ``risk_flags`` 只允许使用 :data:`KNOWN_RISK_FLAGS`。

        早失败：定义阶段就拦截拼写错误，避免脏数据进库。
        """
        unknown = set(value) - KNOWN_RISK_FLAGS
        if unknown:
            raise ValueError(
                f"unknown risk flags: {sorted(unknown)}; "
                f"allowed: {sorted(KNOWN_RISK_FLAGS)}"
            )
        return value

    def to_structure_payload(self) -> dict[str, Any]:
        """把 beats / shots / duration 范围序列化为 ``structure`` JSON。

        最终落库结构（与计划文档 B.2 节约定一致）：
        ``{"beats": [...], "total_shots_range": [a, b], "duration_sec_range": [a, b]}``
        """
        return {
            "beats": [beat.model_dump() for beat in self.beats],
            "total_shots_range": list(self.total_shots_range),
            "duration_sec_range": list(self.duration_sec_range),
        }


# ---------------------------------------------------------------------------
# 6 条中国市场爆款公式（P1 内置）
# ---------------------------------------------------------------------------


_UNDERDOG_TRIUMPH_DIALOG = (
    "【低谷·18s · 特写】\n"
    "镜头：办公室角落，主角{character}低头被同事讥讽。\n"
    "台词：同事甲：“你这种连基础{audience_pain}都搞不定的，趁早回老家吧。”\n"
    "主角（画外独白）：“我不是不行，我只是没遇到对的{product_name}。”\n\n"
    "【转折·12s · 手—物—脸】\n"
    "镜头：手部特写打开{product_name}包装盒，灯光在产品上反光，"
    "切到主角眼神由黯淡转坚定。\n"
    "字幕：当{product_name}遇见我，命运按下了重置键。\n\n"
    "【翻转·30s · 远景拉变焦】\n"
    "镜头：会议室全景，主角站起来，手持{product_name}做出关键操作；"
    "镜头从远到近推到产品再到对方瞠目结舌的脸。\n"
    "台词：主角：“{competitor_alt}做不到的，{product_name}帮我做到了。”\n"
    "同事甲（错愕）：“你……什么时候开始变得这么强？”\n"
    "字幕：底层翻身从来不靠运气，靠选对工具。\n"
    "（屏幕右下角持续显示“演绎”字样）"
)

_UNDERDOG_TRIUMPH = FormulaDefinition(
    id="underdog_triumph",
    name="凡人逆袭",
    region=FormulaRegion.cn,
    category="cn_viral",
    beats=[
        Beat(
            id="low_point",
            duration_sec=18,
            function="建立羞辱处境与共情起点：主角被同侪/上司/家人低估",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="turning_point",
            duration_sec=12,
            function="产品/装备入场，切换主角心境",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="triumph",
            duration_sec=30,
            function="反转 + 见证者反应：让旁观者替观众发出惊叹",
            shot_type="wide_shot",
            recommended_camera_movement="zoom_out",
        ),
    ],
    total_shots_range=(3, 5),
    duration_sec_range=(60, 90),
    risk_flags=["requires_yanyi_label", "class_sensitivity"],
    sample_dialog=_UNDERDOG_TRIUMPH_DIALOG,
    typical_duration_sec=60,
    typical_shot_count=4,
    psychology=(
        "替代性满足（vicarious satisfaction）+ 自我投射：研究显示约 85% 的"
        "中国短剧主角设定为下沉市场或被边缘化人群，观众通过观看主角逆袭，"
        "完成对自身现实困境的心理代偿。强翻转节奏（前 30 秒抑、后 30 秒扬）"
        "刺激多巴胺释放；产品作为‘装备’介入，承担‘改变命运的钥匙’这一"
        "象征角色，激活‘我也可以拥有’的购买冲动。"
    ),
    use_cases=[
        "职场逆袭（被同事/上司低估后通过工具反超）",
        "校园逆袭（成绩/形象逆袭）",
        "农村/小镇逆袭（家乡返乡创业）",
        "性别逆袭（女性在男性主导场景中胜出）",
        "美貌逆袭（外貌/状态前后反差）",
        "副业逆袭（兼职变主业的故事壳）",
    ],
    avoid_cases=[
        "丑化原雇主、原同事或具体可识别的家庭成员（侵权风险）",
        "过度嘲讽前任或前公司（情绪营销越线）",
        "涉及未成年人受辱场景（平台高压线）",
        "贬低特定地域/职业群体（地域歧视举报风险）",
    ],
    sort_order=10,
)


_CONTRAST_SURPRISE_DIALOG = (
    "【对比 A·15s · 中景】\n"
    "镜头：分屏左侧，主角{character}面对{audience_pain}时手忙脚乱，"
    "反复尝试{competitor_alt}却屡屡失败。\n"
    "台词（旁白）：以前的我，每次遇到{audience_pain}就只能硬扛。\n\n"
    "【产品介入·10s · 手—物—脸】\n"
    "镜头：分屏中央，特写{product_name}在桌面被打开，光线由暗转亮。\n"
    "字幕：直到我换了一种打开方式。\n\n"
    "【对比 B·20s · 中景】\n"
    "镜头：分屏右侧，同一主角同一场景，使用{product_name}后从容应对，"
    "周围人投来意外的眼神。\n"
    "台词：主角：“原来不是我不行，是工具不对。”\n"
    "字幕：同一个我，不同的{product_name}，结果天差地别。\n"
    "（屏幕角标：‘场景演绎’）"
)

_CONTRAST_SURPRISE = FormulaDefinition(
    id="contrast_surprise",
    name="对比反转",
    region=FormulaRegion.cn,
    category="cn_viral",
    beats=[
        Beat(
            id="before_state",
            duration_sec=15,
            function="呈现旧选择/旧状态的不堪，建立痛点锚点",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="product_pivot",
            duration_sec=10,
            function="产品作为分水岭出现，制造视觉切换",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="after_state",
            duration_sec=20,
            function="新状态对照展示，强化锚定效应",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
    ],
    total_shots_range=(2, 3),
    duration_sec_range=(30, 60),
    risk_flags=["requires_yanyi_label", "unverifiable_outcome"],
    sample_dialog=_CONTRAST_SURPRISE_DIALOG,
    typical_duration_sec=45,
    typical_shot_count=3,
    psychology=(
        "对比效应（contrast effect）+ 锚定偏差（anchoring bias）：人脑对"
        "‘前后差异’的感知远强于对‘绝对值’的感知，因此把‘旧我/旧选择’"
        "作为痛苦锚点先压低观众预期，再把产品介入后的状态拉高，差值会被"
        "情绪放大数倍。同一主角的同框对比额外抑制‘是不是模特特殊’这一"
        "怀疑，提高可信度，是化妆/家电/服饰类目最易出爆款的结构。"
    ),
    use_cases=[
        "化妆品妆前/妆后对比",
        "服装搭配前/后对比",
        "智能家电使用前/后效率对比",
        "护肤前/后皮肤状态对比",
        "学习/办公工具前后效率对比",
    ],
    avoid_cases=[
        "极端 P 图式美化（与实拍差距过大触发‘虚假宣传’）",
        "对身材/肤色的歧视性贬低（‘黑/胖=丑’式表达）",
        "对比中暗示治病/医疗效果（医疗器械、医美红线）",
    ],
    sort_order=20,
)


_WORKPLACE_HERO_DIALOG = (
    "【羞辱·15s · 特写】\n"
    "镜头：会议室白板前，主管在白板上画叉，转头看主角{character}。\n"
    "台词：主管：“{character}做的方案永远停留在‘还行’，懂吗，"
    "不是‘还行’能赢下{audience_pain}的。”\n\n"
    "【秘密装备·15s · 手—物—脸】\n"
    "镜头：深夜独居小屋，桌面只剩一盏台灯，主角拆开{product_name}的包装。\n"
    "独白：“我不是没努力，我只是缺一把对的刀。”\n\n"
    "【准备·15s · 中景】\n"
    "镜头：主角连续两晚用{product_name}演练方案，画面快剪展示进度。\n"
    "字幕：48 小时，{product_name}是我唯一的搭档。\n\n"
    "【现场反转·30s · 大远景+推近】\n"
    "镜头：会议室全景，主角自信地展示成果；主管原本要打断的手缓缓放下。\n"
    "台词：主角：“这次我用的是{product_name}，结果你们看屏幕。”\n"
    "同事乙（小声）：“他什么时候变成这样了？”\n\n"
    "【认可·15s · 中景】\n"
    "镜头：主管走过来拍主角肩膀，递过一份新项目书。\n"
    "台词：主管：“项目交给你。”\n"
    "字幕：职场里没有突然的赢家，只有提前装备好的自己。"
)

_WORKPLACE_HERO = FormulaDefinition(
    id="workplace_hero",
    name="职场逆袭",
    region=FormulaRegion.cn,
    category="cn_workplace",
    beats=[
        Beat(
            id="public_shame",
            duration_sec=15,
            function="公开场合被质疑/否定，建立‘必须证明自己’的张力",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="secret_arming",
            duration_sec=15,
            function="独处时获得产品，制造‘私下武装’的反差",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="preparation_montage",
            duration_sec=15,
            function="使用产品突击准备，展示产品功能与主角投入",
            shot_type="medium_shot",
            recommended_camera_movement="track",
        ),
        Beat(
            id="showdown",
            duration_sec=30,
            function="正式场合反转，让原本质疑者亲眼见证",
            shot_type="wide_shot",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="acknowledgement",
            duration_sec=15,
            function="权威方收回质疑、给予认可，完成情绪闭环",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
    ],
    total_shots_range=(4, 6),
    duration_sec_range=(60, 120),
    risk_flags=["class_sensitivity", "requires_yanyi_label"],
    sample_dialog=_WORKPLACE_HERO_DIALOG,
    typical_duration_sec=90,
    typical_shot_count=5,
    psychology=(
        "职业焦虑替代满足 + 仪式化武装：白领观众普遍对‘被否定—被认可’"
        "的剧情极易代入，因为这与现实绩效评估高度同构。‘秘密装备’桥段"
        "把产品定位为‘个人能力的延伸’而非促销品，激活‘投资自己’而非"
        "‘买买买’的合理化叙事，从而提高客单价容忍度，是 3C/办公/学习类"
        "产品最有效的故事壳之一。"
    ),
    use_cases=[
        "项目方案/汇报场景（PPT、办公软件、AI 工具）",
        "考证/晋升场景（学习课程、效率硬件）",
        "新人 vs 老员工的能力反转",
        "跨部门协作中的能力证明（设计、销售、研发互证）",
        "出差/客户拜访前的临场准备",
    ],
    avoid_cases=[
        "把整家公司或具体行业整体污名化",
        "暗示‘买了就能升职加薪’的不可验证承诺",
        "塑造极端讨好上司型主角（PUA 隐喻引发反感）",
        "贬低同事人格（性别/学历/出身）",
    ],
    sort_order=30,
)


_FAMILY_CONFLICT_DIALOG = (
    "【张力·15s · 中景】\n"
    "镜头：晚饭桌上，{character}与家人因{audience_pain}起口角，气氛压抑。\n"
    "台词：家人：“你做的这些都没用，跟当年一样。”\n\n"
    "【否定·15s · 特写】\n"
    "镜头：主角独自在阳台抽烟/泡茶，眼眶微红。\n"
    "独白：“我不是不想做好，我只是从来没找到合适的方法。”\n\n"
    "【悄然介入·15s · 手—物—脸】\n"
    "镜头：第二天，主角默默把{product_name}放进家庭的日常场景里。\n"
    "字幕：有时候改变关系的不是争吵，而是一件被认真挑选过的小东西。\n\n"
    "【缓和·20s · 中景】\n"
    "镜头：家人无意中使用了{product_name}后表情变化，主动开口和缓。\n"
    "台词：家人：“这……是你买的？”\n"
    "主角：“嗯，我想试试。”\n\n"
    "【温暖收束·10s · 远景】\n"
    "镜头：客厅灯光柔和，三代人围坐，{product_name}作为日常物品自然出现。\n"
    "字幕：家人之间的和解，常常是从一件小事被认真对待开始的。\n"
    "（左下角持续显示‘剧情演绎’字样）"
)

_FAMILY_CONFLICT = FormulaDefinition(
    id="family_conflict",
    name="家庭冲突",
    region=FormulaRegion.cn,
    category="cn_family",
    beats=[
        Beat(
            id="friction",
            duration_sec=15,
            function="呈现家庭张力但不展示对骂、限制激烈程度",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="perceived_failure",
            duration_sec=15,
            function="主角内心独白，建立同情视角而不强化对家人的攻击",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="product_intervention",
            duration_sec=15,
            function="产品作为‘善意行动’而非‘炫耀工具’介入家庭场景",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="reconciliation",
            duration_sec=20,
            function="家人态度软化（行为而非台词），避免谁输谁赢",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="warm_close",
            duration_sec=10,
            function="温情收束，输出‘共同变好’的价值落点",
            shot_type="wide_shot",
            recommended_camera_movement="dolly_out",
        ),
    ],
    total_shots_range=(4, 6),
    duration_sec_range=(60, 90),
    risk_flags=[
        "family_conflict_compliance",
        "class_sensitivity",
        "requires_yanyi_label",
        "gender_sensitivity",
    ],
    sample_dialog=_FAMILY_CONFLICT_DIALOG,
    typical_duration_sec=75,
    typical_shot_count=5,
    psychology=(
        "家庭关系修复幻想 + 投射机制：家庭关系是中国短视频用户最常被触动"
        "的情感切口，但同时也是平台审核高压区。结构必须把‘冲突 → 行动 → "
        "和解’做成软曲线（不是‘骂赢家人’），让产品成为‘修复关系的契机’"
        "而非‘报复工具’；这样既能调动情感，又能规避‘丑化父母/婆媳互骂’"
        "导致的限流与封号风险。"
    ),
    use_cases=[
        "家居清洁/厨房用品（让做饭这件事变得不再是负担）",
        "亲子教育/学习用品（缓解家长焦虑）",
        "健康养生类（关心父母身体）",
        "礼物属性场景（节庆送礼桥段）",
    ],
    avoid_cases=[
        "婆媳互骂式正面冲突（高概率限流）",
        "子女对父母的控诉/审判式独白",
        "把家庭成员塑造成完全负面的‘反派’",
        "暗示‘只有买了才是孝顺’的道德绑架",
        "涉及离婚/重男轻女等敏感家庭议题做戏剧化处理",
    ],
    sort_order=40,
)


_MYSTERY_TWIST_DIALOG = (
    "【钩子·10s · 特写+推近】\n"
    "镜头：黑底白字“为什么她总是比同龄人显小 10 岁？”\n"
    "切到主角{character}站在镜子前，神秘一笑。\n\n"
    "【误导·15s · 中景】\n"
    "镜头：罗列三种常见猜测——基因、医美、滤镜，每种猜测都画上红叉。\n"
    "字幕：都不是。\n"
    "台词（旁白）：直到一位粉丝翻到她梳妆台，才发现真正的秘密。\n\n"
    "【揭示·20s · 手—物—脸】\n"
    "镜头：粉丝抽屉里抽出{product_name}，主角拿起，对着镜头展示成分/卖点。\n"
    "台词：主角：“我每天只做了一件事——用{product_name}对付{audience_pain}。”\n\n"
    "【兑现·15s · 中景】\n"
    "镜头：使用过程演示，配合数据/前后对比小图（注明‘个人体验，仅供参考’）。\n"
    "字幕：神秘配方不神秘，认真挑选才神秘。\n"
    "（屏幕角标：‘演绎’ + ‘个人体验，效果因人而异’）"
)

_MYSTERY_TWIST = FormulaDefinition(
    id="mystery_twist",
    name="悬疑反转",
    region=FormulaRegion.cn,
    category="cn_viral",
    beats=[
        Beat(
            id="hook_question",
            duration_sec=10,
            function="抛出引人好奇的问题，制造好奇心缺口",
            shot_type="close_up",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="misdirect",
            duration_sec=15,
            function="罗列错误猜测，进一步拉大缺口",
            shot_type="medium_shot",
            recommended_camera_movement="pan",
        ),
        Beat(
            id="reveal",
            duration_sec=20,
            function="揭示答案就是产品，给到强视觉冲击",
            shot_type="hand_object_face",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="resolution",
            duration_sec=15,
            function="兑现承诺，提供可信度（数据/演示/免责）",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
    ],
    total_shots_range=(3, 5),
    duration_sec_range=(45, 75),
    risk_flags=["requires_yanyi_label", "unverifiable_outcome"],
    sample_dialog=_MYSTERY_TWIST_DIALOG,
    typical_duration_sec=60,
    typical_shot_count=4,
    psychology=(
        "好奇心缺口理论（Loewenstein 1994）：当观众感知到‘已知 vs 想知’"
        "之间存在缺口，注意力会被强制锁定，直到缺口被填平。该公式专门"
        "把‘缺口’做大、把‘揭晓’做爽，因此完播率天然高。但‘揭晓即产品’"
        "极易演变为夸大宣传，必须在 ``resolution`` 节拍内附上免责并避免"
        "医疗/收益类承诺。"
    ),
    use_cases=[
        "‘神秘成分’切入的护肤/食品/保健品",
        "‘神秘配方/算法’切入的智能产品",
        "‘神秘习惯/做法’切入的生活方式品",
        "‘神秘工具’切入的办公/学习产品",
    ],
    avoid_cases=[
        "暗示治病/抗衰/抗癌等不可验证效果",
        "用戏剧化数字（如‘瘦 30 斤’）做卖点",
        "用‘行业内幕揭秘’口吻贬低竞品",
        "用‘秘方’暗示无证/三无产品的合规感",
    ],
    sort_order=50,
)


_TIME_TRAVEL_DIALOG = (
    "【现实·15s · 中景】\n"
    "镜头：主角{character}下班回家，瘫在沙发上面对一堆{audience_pain}。\n"
    "独白：“如果时间能倒回去，我一定不会让自己再过这种日子。”\n\n"
    "【穿越·10s · 特写+变焦】\n"
    "镜头：手中的{product_name}被打开，画面光晕闪烁，时空隧道意象。\n"
    "字幕：当一件好东西出现，就是另一种‘穿越’。\n\n"
    "【对话·20s · 中景】\n"
    "镜头：分屏出现‘过去/未来的自己’，与现在的自己对话。\n"
    "台词：未来的自己：“你以后会因为今天用了{product_name}，少走两年弯路。”\n"
    "现在的自己（苦笑）：“真的假的？”\n"
    "未来的自己：“你试试就知道。”\n\n"
    "【产品桥梁·20s · 手—物—脸】\n"
    "镜头：现在的自己开始使用{product_name}，画面节奏从迟缓变明快。\n"
    "字幕：你不需要真的穿越，只需要早一点遇见对的{product_name}。\n\n"
    "【回归·15s · 大远景】\n"
    "镜头：主角带着新状态走出门，城市灯光在身后亮起。\n"
    "字幕：与其后悔，不如现在就开始。\n"
    "（屏幕右下角持续显示‘演绎/虚构’字样）"
)

_TIME_TRAVEL = FormulaDefinition(
    id="time_travel",
    name="时空穿越",
    region=FormulaRegion.cn,
    category="cn_viral",
    beats=[
        Beat(
            id="present_self",
            duration_sec=15,
            function="呈现当下困境，建立‘想要改变’的内在动机",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="portal_moment",
            duration_sec=10,
            function="产品/事件触发时空感，制造叙事拐点",
            shot_type="close_up",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="alternate_self_dialogue",
            duration_sec=20,
            function="过去/未来自我对话，明确改变的代价与价值",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="product_bridge",
            duration_sec=20,
            function="产品作为时空桥梁出现，完成承诺的转化",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="return_renewed",
            duration_sec=15,
            function="主角回到现实但带回新状态，给观众‘可达成感’",
            shot_type="wide_shot",
            recommended_camera_movement="dolly_out",
        ),
    ],
    total_shots_range=(4, 7),
    duration_sec_range=(60, 90),
    risk_flags=["requires_yanyi_label"],
    sample_dialog=_TIME_TRAVEL_DIALOG,
    typical_duration_sec=80,
    typical_shot_count=5,
    psychology=(
        "自我对话（self-talk）+ 后悔规避（regret aversion）：人对‘错过’"
        "的痛苦感受强于对‘获得’的喜悦（前景理论）。让‘未来的自己’对"
        "‘现在的自己’说话，把购买决策包装成‘避免后悔’而非‘消费冲动’，"
        "在长决策周期品类（学习、健康、护肤、智能硬件）转化效果尤其显著。"
    ),
    use_cases=[
        "学习/成长类（早一点学习换更好未来）",
        "护肤/抗衰类（早一点保养避免日后修复）",
        "健康/运动类（早一点改变避免身体代价）",
        "理财/工具类（早一点开始避免错过红利）",
        "亲子教育类（早一点投入避免孩子掉队）",
    ],
    avoid_cases=[
        "暗示具体收益数字（‘多赚百万’‘多活十年’）",
        "把不使用产品的人塑造成‘失败的未来’制造焦虑",
        "通过年龄羞辱推动购买（‘你不买就老得快’）",
    ],
    sort_order=60,
)


# ---------------------------------------------------------------------------
# 6 条国际经典叙事公式（global，W11-T1 P2 阶段）
# ---------------------------------------------------------------------------
# 与 cn 公式的关键差异：
# - region 全部为 ``FormulaRegion.global_``，category 走 ``global_*`` 子族；
# - sample_dialog 采用‘英文骨架 + 中文落点’的混排，便于跨语言品牌复用；
# - 风险标记仅出现在‘易夸大效果’的几条上（hero / scqa / pas_bab），
#   家庭/阶层/性别等地区性合规风险默认不附加（由全球分发渠道自行兜底）。
# ---------------------------------------------------------------------------


_HEROS_JOURNEY_DIALOG = (
    "【Ordinary World·15s · 特写】\n"
    "镜头：清晨写字楼里，{character} 重复着每天 9 点打卡的动作，"
    "桌上的咖啡早已凉透。\n"
    "旁白（英文字幕）：Every hero begins in a world that no longer fits.\n"
    "独白：“This is fine. 这样过下去也行……吧？”\n\n"
    "【Call to Adventure·15s · 中景】\n"
    "镜头：邮箱弹出一封邀请，落款是 {hero_archetype}。\n"
    "台词（导师）：“你确定要在这里耗一辈子？{product_name} 不是答案，"
    "是入口。”\n"
    "字幕：The call rarely comes when convenient.\n\n"
    "【Crossing the Threshold·20s · 手—物—脸】\n"
    "镜头：{character} 第一次打开 {product_name}，光从屏幕里涌出来。\n"
    "独白：“OK, let's see what's on the other side.”\n"
    "字幕：每一次跨越门槛，都是与旧自我的告别。\n\n"
    "【Trials & Tests·25s · 中景跟随】\n"
    "镜头：连续切换三个失败场景，{character} 在 {product_name} 的引导"
    "下迭代。\n"
    "台词：“{competitor_alt} 帮不了我，但这一次我不想再放弃。”\n"
    "字幕：Failure is the tuition fee for transformation.\n\n"
    "【Ordeal·25s · 特写推近】\n"
    "镜头：关键时刻，{character} 面对 {audience_pain} 最严酷的版本。\n"
    "独白：“If I quit now, I go back to who I was.”\n"
    "字幕：The ordeal is where the real hero is born.\n\n"
    "【Reward·25s · 远景拉变焦】\n"
    "镜头：{character} 完成挑战，{product_name} 在场景中被举起，"
    "像是‘信物’。\n"
    "台词：“It wasn't just a tool. It was the bridge.”\n"
    "字幕：Reward 不是终点，而是让你能照亮别人的火把。\n\n"
    "【Return Transformed·25s · 大远景拉远】\n"
    "镜头：{character} 回到熟悉的城市，但走路的姿态已经不同。\n"
    "旁白：The hero returns, not the same.\n"
    "字幕：你的故事，从打开 {product_name} 那一刻开始。\n"
    "（屏幕角标持续显示“故事演绎，效果因人而异”）"
)

_HEROS_JOURNEY = FormulaDefinition(
    id="heros_journey",
    name="英雄之旅",
    region=FormulaRegion.global_,
    category="global_classic",
    beats=[
        Beat(
            id="ordinary_world",
            duration_sec=15,
            function="建立主角的‘旧世界’与缺憾感，让观众代入 baseline",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="call_to_adventure",
            duration_sec=15,
            function="导师/事件/产品作为召唤者出现，制造离开舒适区的钩子",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="crossing_threshold",
            duration_sec=20,
            function="主角接受召唤、首次使用产品，完成与旧自我的告别",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="trials_and_tests",
            duration_sec=25,
            function="一系列试炼/小挫折，强化产品作为‘旅伴’的角色",
            shot_type="medium_shot",
            recommended_camera_movement="track",
        ),
        Beat(
            id="ordeal_climax",
            duration_sec=25,
            function="终极考验：把痛点放大到极致，逼出主角真正的转变",
            shot_type="close_up",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="reward_seized",
            duration_sec=25,
            function="主角胜出、收获关键奖赏，产品被定位为‘神器’",
            shot_type="wide_shot",
            recommended_camera_movement="zoom_out",
        ),
        Beat(
            id="return_transformed",
            duration_sec=25,
            function="带着新状态归来，把奖赏分享给所属社群，完成情感闭环",
            shot_type="wide_shot",
            recommended_camera_movement="dolly_out",
        ),
    ],
    total_shots_range=(5, 9),
    duration_sec_range=(120, 180),
    risk_flags=["unverifiable_outcome"],
    sample_dialog=_HEROS_JOURNEY_DIALOG,
    typical_duration_sec=150,
    typical_shot_count=7,
    psychology=(
        "神话单元（monomyth）是 Joseph Campbell 在《千面英雄》中归纳出的"
        "跨文化叙事原型，几乎所有打动观众的故事——从《星球大战》到苹果发布会"
        "——都可以套进‘离开 → 启程 → 试炼 → 蜕变 → 归来’这条曲线。它有效"
        "的根源在于：观众的潜意识把主角的旅程映射到自己的成长史，产品被定位"
        "成英雄路上的‘神器’，既不喧宾夺主又承担推动剧情的关键作用。它特别"
        "适合品牌起源故事、创业历程、产品发布会等需要‘仪式感’的内容，"
        "但代价是节奏偏长，必须配合至少 120 秒时长，否则压缩后会失去‘缓慢"
        "累积 → 爆发’的情绪张力。"
    ),
    use_cases=[
        "产品发布会与品牌起源故事（赋予仪式感）",
        "创业者历程纪录片 / 创始人专访短片",
        "励志成长类（学习、健身、技能、职业转型）",
        "公益倡议（呼吁观众加入‘旅程’）",
        "节庆主题大片（年终回顾、品牌周年）",
    ],
    avoid_cases=[
        "短促时长（<60 秒，无法承载完整曲线）",
        "纯功能性产品广告（卖点直给即可，不需要史诗感）",
        "极简主义品牌（与‘宏大叙事’调性冲突）",
        "高频复购的快消品（每条都用英雄之旅会迅速疲劳）",
    ],
    sort_order=70,
)


_PIXAR_STORY_SPINE_DIALOG = (
    "【Once Upon a Time·10s · 远景】\n"
    "镜头：温暖的家，{character} 与家人围坐，{product_name} 还未出现。\n"
    "旁白：Once upon a time, there was a family that had everything except"
    " {audience_pain} 的解法。\n\n"
    "【Every Day·10s · 中景】\n"
    "镜头：每天清晨，相同的早餐桌、相同的争执、相同的妥协。\n"
    "旁白：Every day, they made do.\n"
    "字幕：日子像复印件一样过着。\n\n"
    "【One Day·15s · 特写推近】\n"
    "镜头：邮箱里出现 {product_name} 的样品盒，盒子上的彩绘像童话扉页。\n"
    "台词：{character}：“What if today is different?”\n"
    "字幕：One day, something arrived that didn't belong to yesterday.\n\n"
    "【Because of That·15s · 手—物—脸】\n"
    "镜头：因为 {product_name} 出现在桌上，孩子第一次主动帮忙；"
    "妈妈第一次有时间坐下来喝完一杯茶。\n"
    "旁白：Because of that, small things became gentle things.\n\n"
    "【Until Finally·15s · 中景】\n"
    "镜头：饭桌从沉默变成笑声，{character} 看见家人拿起 {product_name}"
    " 不再迟疑。\n"
    "台词：家人：“I didn't know it could feel like this.”\n"
    "字幕：Until finally, the room sounded like a home again.\n\n"
    "【And Ever Since·10s · 远景拉远】\n"
    "镜头：阳光透过窗帘，{product_name} 自然地放在桌角，"
    "像家庭的新成员。\n"
    "旁白：And ever since, the ordinary became something to look forward to.\n"
    "字幕：温柔的故事，不需要英雄。"
)

_PIXAR_STORY_SPINE = FormulaDefinition(
    id="pixar_story_spine",
    name="Pixar 故事脊柱",
    region=FormulaRegion.global_,
    category="global_emotional",
    beats=[
        Beat(
            id="once_upon_a_time",
            duration_sec=10,
            function="建立主角与所处世界的初始平衡，给观众安全感",
            shot_type="wide_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="every_day",
            duration_sec=10,
            function="呈现日常重复感，铺设‘看似正常其实有缺’的心理底色",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="one_day",
            duration_sec=15,
            function="一个轻微扰动开启故事，产品作为‘扰动者’登场",
            shot_type="close_up",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="because_of_that",
            duration_sec=15,
            function="连锁反应：每个变化都因前一变化而生，体现因果",
            shot_type="hand_object_face",
            recommended_camera_movement="track",
        ),
        Beat(
            id="until_finally",
            duration_sec=15,
            function="情感高点抵达，主角与世界关系完成温柔的重塑",
            shot_type="medium_shot",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="and_ever_since",
            duration_sec=10,
            function="新平衡定格，产品自然内化为日常的一部分",
            shot_type="wide_shot",
            recommended_camera_movement="dolly_out",
        ),
    ],
    total_shots_range=(4, 6),
    duration_sec_range=(60, 90),
    risk_flags=[],
    sample_dialog=_PIXAR_STORY_SPINE_DIALOG,
    typical_duration_sec=75,
    typical_shot_count=6,
    psychology=(
        "Pixar 在内部培训中提炼出的 6 段‘故事脊柱’是连孩子也能听懂的最小"
        "叙事骨架。它的力量来自‘every day → one day → because of that →"
        " until finally’这条情绪斜坡：先把观众放回熟悉感中，再用一个轻微的"
        "扰动开启故事，最后通过连锁反应抵达情感高点。这种结构非常适合家庭、"
        "宠物、教育、母婴类温情品牌，能在 60–90 秒内完成完整的情绪曲线，"
        "而不会让观众感觉‘被销售’，因此特别适合品牌的长期内容（content"
        " engine）而非促销广告。"
    ),
    use_cases=[
        "家庭情感类商品（厨电、家居、清洁、家电）",
        "萌宠商品（宠粮、玩具、宠物医疗周边）",
        "教育产品（亲子学习、绘本、玩具）",
        "文创周边与节庆送礼场景",
        "母婴 / 育儿用品的温情向内容",
    ],
    avoid_cases=[
        "严肃 / 技术类商品（B2B、工业品、企业服务）",
        "老年人或权威感主导的受众（与童话感不符）",
        "需要严肃决策的高客单（金融、医疗、企业服务）",
        "黑色幽默 / 反讽类品牌（与温情叙事冲突）",
    ],
    sort_order=80,
)


_THREE_ACT_DIALOG = (
    "【Setup·Act 1 World·15s · 远景】\n"
    "镜头：城市清晨的天际线，镜头从城市拉到一个普通公寓，{character} 起床、"
    "刷牙、出门。\n"
    "旁白：In a world that asks too much and rewards too little……\n\n"
    "【Inciting Incident·15s · 中景】\n"
    "镜头：{character} 在地铁里看到一则关于 {product_name} 的故事，"
    "第一次被打动。\n"
    "台词（旁观者）：“Looks like exactly the thing she needs.”\n"
    "字幕：The story changes when the question is finally asked.\n\n"
    "【Rising Action·Act 2·25s · 中景跟随】\n"
    "镜头：{character} 把 {product_name} 带回生活，连续三次试用、"
    "三次微调，每一次都更接近答案。\n"
    "独白：“Why didn't I find this sooner?”\n"
    "字幕：成长不是一夜之间，而是一个个小决定的叠加。\n\n"
    "【Midpoint Twist·15s · 特写推近】\n"
    "镜头：第一次真正的困难出现，{audience_pain} 比预期更顽固。\n"
    "台词：“Maybe I was wrong about this.”\n"
    "字幕：A story without a midpoint twist is just a list of events.\n\n"
    "【Dark Moment·15s · 特写】\n"
    "镜头：{character} 独自坐在窗边，桌上的 {product_name} 静静躺着。\n"
    "独白：“If even this can't help me, what can?”\n"
    "字幕：英雄都会有想放弃的瞬间。\n\n"
    "【Climax·Act 3·20s · 远景拉变焦】\n"
    "镜头：{character} 重新拿起 {product_name}，做出关键选择；"
    "周围人见证她的改变。\n"
    "台词：“I'm done waiting for permission.”\n"
    "字幕：The third act is not about luck. It's about choosing to stand up"
    " again.\n\n"
    "【New Equilibrium·15s · 大远景】\n"
    "镜头：城市灯光在背景亮起，{character} 走出门，{product_name}"
    " 已成为日常。\n"
    "旁白：The world looks the same. She doesn't.\n"
    "字幕：每一个三幕故事，都是关于‘回到起点却不再是起点’。"
)

_THREE_ACT = FormulaDefinition(
    id="three_act",
    name="三幕结构",
    region=FormulaRegion.global_,
    category="global_classic",
    beats=[
        Beat(
            id="setup_world",
            duration_sec=15,
            function="第一幕：建立世界、人物、与‘缺憾感’，给观众坐标系",
            shot_type="wide_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="inciting_incident",
            duration_sec=15,
            function="触发事件，把人物推出舒适区，开启第二幕",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="rising_action",
            duration_sec=25,
            function="第二幕上升：连续小胜与小败，刻画成长曲线",
            shot_type="medium_shot",
            recommended_camera_movement="track",
        ),
        Beat(
            id="midpoint_twist",
            duration_sec=15,
            function="第二幕中点：方向反转，让目标变得更难",
            shot_type="close_up",
            recommended_camera_movement="zoom_in",
        ),
        Beat(
            id="dark_moment",
            duration_sec=15,
            function="第二幕低点：‘all is lost’时刻，逼出主角真正的决断",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="climax",
            duration_sec=20,
            function="第三幕高潮：兑现承诺，让人物完成内在与外在的双重抵达",
            shot_type="wide_shot",
            recommended_camera_movement="zoom_out",
        ),
        Beat(
            id="new_equilibrium",
            duration_sec=15,
            function="收束新常态：世界看似相同，但主角已不同",
            shot_type="wide_shot",
            recommended_camera_movement="dolly_out",
        ),
    ],
    total_shots_range=(6, 9),
    duration_sec_range=(90, 180),
    risk_flags=[],
    sample_dialog=_THREE_ACT_DIALOG,
    typical_duration_sec=120,
    typical_shot_count=7,
    psychology=(
        "三幕结构是西方戏剧自亚里士多德以来最稳定的叙事容器：第一幕铺设"
        "世界与人物，第二幕通过冲突逼迫人物改变，第三幕兑现承诺。它在 90"
        "–180 秒的中长视频里是最‘安全’的选择，因为观众的潜意识对这条曲"
        "线已经有完整预期，创作者只需把品牌放在合适位置（通常作为催化剂或"
        "试炼）。它的代价是必须在 setup 与 rising action 上花足够时间，"
        "过短的视频反而会显得刻意，因此不适合需要前 3 秒就爆点的强 CTR"
        "信息流场景。"
    ),
    use_cases=[
        "通用品牌故事（多受众、多场景）",
        "多人物剧情（人物间存在张力）",
        "品牌纪录片 / 微电影",
        "产品发布前的预热‘旅程’",
        "跨季营销主题大片",
    ],
    avoid_cases=[
        "极短时长（<45 秒，无法完整呈现三幕）",
        "追求‘信息密度大于情绪曲线’的硬广",
        "仅有单一卖点、不存在转折的简单产品",
        "信息流前 3 秒必须爆点的强 CTR 场景",
    ],
    sort_order=90,
)


_SCQA_DIALOG = (
    "【Situation·10s · 远景】\n"
    "镜头：会议室全景，{character} 是 CEO，PPT 显示业务过去三年的稳定曲线。\n"
    "旁白：For three years, {audience_pain} was something we managed,"
    " not solved.\n"
    "字幕：Situation：行业里所有人都这么做。\n\n"
    "【Complication·10s · 中景推近】\n"
    "镜头：曲线突然下滑，会议室的笑容变成沉默。\n"
    "台词：高管：“Same playbook, different outcomes. That's the new"
    " normal.”\n"
    "字幕：Complication：旧地图找不到新大陆。\n\n"
    "【Question·10s · 特写】\n"
    "镜头：{character} 站在白板前写下三个字：Then what?\n"
    "独白：“If everything that worked before stops working, where do we"
    " look?”\n"
    "字幕：Question：决策者真正需要回答的，从来不是‘怎么做’，而是‘做什么’。\n\n"
    "【Answer·15s · 手—物—脸】\n"
    "镜头：{character} 把 {product_name} 接入企业系统，仪表盘指标在 24 "
    "小时内重新跑动。\n"
    "台词：“{product_name} doesn't replace the team. It gives the team"
    " back its time.”\n"
    "字幕：Answer：不是更多努力，而是更聪明的杠杆。\n"
    "（屏幕角标“案例演绎，实施效果与企业上下文相关”）"
)

_SCQA = FormulaDefinition(
    id="scqa",
    name="SCQA 商务叙事",
    region=FormulaRegion.global_,
    category="global_business",
    beats=[
        Beat(
            id="situation",
            duration_sec=10,
            function="陈述受众已知现状，让对方点头，建立认知共识",
            shot_type="wide_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="complication",
            duration_sec=10,
            function="抛出复杂化变量，让对方紧张：旧路径开始失效",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="question",
            duration_sec=10,
            function="把张力凝结成一个决策问题，让对方主动思考",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="answer",
            duration_sec=15,
            function="给出基于产品的清晰答案，强调‘杠杆’而非‘加班’",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
    ],
    total_shots_range=(3, 5),
    duration_sec_range=(30, 60),
    risk_flags=["unverifiable_outcome"],
    sample_dialog=_SCQA_DIALOG,
    typical_duration_sec=45,
    typical_shot_count=4,
    psychology=(
        "SCQA 由 McKinsey 顾问提出，是 Barbara Minto‘金字塔写作法’的口语化"
        "版本。它把任何复杂论述压缩为四步：现状（让对方点头）、复杂化（让"
        "对方紧张）、提问（让对方主动思考）、回答（提供你早就准备好的答案"
        "）。这条公式不是讲故事，而是模拟决策路径，因此特别适合 B2B、SaaS、"
        "企业服务等需要‘先博取信任再做承诺’的高客单价品类；情感型快消品"
        "请勿使用，会显得冷漠且与品类调性冲突。"
    ),
    use_cases=[
        "B2B 产品 / SaaS 上线介绍",
        "企业服务（咨询、IT、安全、合规）",
        "高端消费品（说服决策者，不只是激发情绪）",
        "行业大会演讲短片",
        "投资者关系沟通片段",
    ],
    avoid_cases=[
        "情感型快消品（情绪 > 逻辑的品类）",
        "短直效响应广告（<30s 不够铺设‘情境’）",
        "受众已经熟知行业现状的内行用户（铺垫显冗长）",
        "需要突出‘人’而非‘问题’的品牌故事",
    ],
    sort_order=100,
)


_STORYBRAND_SB7_DIALOG = (
    "【Character·8s · 特写】\n"
    "镜头：{character} 是一名独立咨询师，桌上堆满她为客户解决问题的笔记。\n"
    "旁白：Every story has a hero. Today's hero is you.\n"
    "字幕：你，就是这个故事的主角。\n\n"
    "【Problem·10s · 中景推近】\n"
    "镜头：客户在电话那头发火；{character} 关上电脑，疲惫地揉着眉心。\n"
    "台词（客户）：“I just need it to work. Not another tool, not another"
    " framework.”\n"
    "字幕：External：工具太多，时间太少。Internal：永远像在追赶。\n\n"
    "【Guide·12s · 中景】\n"
    "镜头：{product_name} 出现在画面里，不是在炫技，而是在‘倾听’。\n"
    "旁白：A good guide doesn't put themselves in the spotlight."
    " They put the hero there.\n"
    "字幕：{product_name} 不是你的解决方案，而是你的副驾驶。\n\n"
    "【Plan·10s · 手—物—脸】\n"
    "镜头：三步骤清单出现：1) Connect 2) Configure 3) Confirm。\n"
    "台词：“Here is the plan. Three steps. One outcome.”\n"
    "字幕：清晰的计划比好听的承诺更可信。\n\n"
    "【Call to Action·10s · 中景推近】\n"
    "镜头：{character} 点击‘开始’，画面切到一个直接的按钮。\n"
    "字幕（直接 CTA）：Start your first project with {product_name} today.\n\n"
    "【Success·15s · 远景拉变焦】\n"
    "镜头：{character} 在咖啡馆悠然地与客户开会，工作没有压垮生活。\n"
    "旁白：This is what success looks like when the hero has the right"
    " guide.\n"
    "字幕：你想要的人生节奏，{product_name} 帮你扛住。\n\n"
    "【Failure Avoidance·10s · 特写】\n"
    "镜头：闪回到上一段‘无 guide’的疲惫日常，但语气是‘你不必再回到那里’。\n"
    "旁白：Without the right guide, every day looks like the last.\n"
    "字幕：故事的反面不是失败，是停滞。"
)

_STORYBRAND_SB7 = FormulaDefinition(
    id="storybrand_sb7",
    name="StoryBrand SB7 框架",
    region=FormulaRegion.global_,
    category="global_business",
    beats=[
        Beat(
            id="character_introduced",
            duration_sec=8,
            function="把客户而不是品牌设定为主角，触发自我聚焦",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="problem_revealed",
            duration_sec=10,
            function="同时揭示外在问题与内在感受，建立深层共情",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="guide_appears",
            duration_sec=12,
            function="品牌作为‘向导’出现，强调倾听与同理心",
            shot_type="medium_shot",
            recommended_camera_movement="static",
        ),
        Beat(
            id="plan_unveiled",
            duration_sec=10,
            function="三步骤的清晰计划，把抽象解决方案落到可执行步骤",
            shot_type="hand_object_face",
            recommended_camera_movement="track",
        ),
        Beat(
            id="call_to_action",
            duration_sec=10,
            function="给出直接、不含糊的下一步动作（CTA）",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="success_vision",
            duration_sec=15,
            function="描绘‘成功后的生活’具象画面，强化目标感",
            shot_type="wide_shot",
            recommended_camera_movement="zoom_out",
        ),
        Beat(
            id="failure_avoided",
            duration_sec=10,
            function="温和提示‘不行动的代价’，触发损失厌恶但不制造焦虑",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
    ],
    total_shots_range=(5, 8),
    duration_sec_range=(60, 90),
    risk_flags=[],
    sample_dialog=_STORYBRAND_SB7_DIALOG,
    typical_duration_sec=75,
    typical_shot_count=7,
    psychology=(
        "StoryBrand 的核心反转是‘客户才是英雄，品牌只是向导’。Donald"
        " Miller 把神话原型简化为 7 个清单要素：人物—问题—向导—计划—呼吁—"
        "成功—失败，方便商业内容快速复用。它的心理学根据是‘自我聚焦偏差’"
        "：人只对‘和我有关的故事’投入注意力；把品牌放在‘向导’位置而不是"
        "‘主角’位置，会显著提高观众的代入感与转化率。它最适合服务型、咨询"
        "型、解决方案型品牌；缺点是过于线性，不适合多人物、复杂情节剧。"
    ),
    use_cases=[
        "服务型品牌（咨询、教练、培训、医疗服务）",
        "解决方案导向品牌（SaaS、工具类应用）",
        "个体创业者 / 独立顾问 / 教练等‘以人立品’角色",
        "数字产品落地页 / Onboarding 短片",
        "课程销售短视频",
    ],
    avoid_cases=[
        "多角色、复杂剧情的剧情向内容",
        "强调‘品牌即英雄’的奢侈品 / 文化品牌",
        "不需要明确 CTA 的形象广告",
        "纪录片 / 散文化叙事内容",
    ],
    sort_order=110,
)


_PAS_BAB_DIALOG = (
    "【Pain·10s · 特写静止】\n"
    "镜头：{character} 凌晨两点盯着屏幕，{audience_pain} 把一切搞砸。\n"
    "独白（字幕同步）：This is the third time this week. I can't keep"
    " doing this.\n"
    "字幕：Pain：你以为只是今天，但其实是每天。\n\n"
    "【Agitate·10s · 中景推近】\n"
    "镜头：闹钟响、咖啡洒、客户来电同时炸响，节奏剪辑加快。\n"
    "台词：“I tried {competitor_alt}. I tried harder. I tried earlier.”\n"
    "字幕：Agitate：你试过的方法不是不努力，而是方向错了。\n"
    "       Before：总是疲于救火。\n\n"
    "【Solution / Bridge·15s · 手—物—脸】\n"
    "镜头：{product_name} 接入工作流，画面节奏从混乱切到整齐有序。\n"
    "台词：“{product_name} didn't make it easier. It made it possible.”\n"
    "字幕：Solution：让你不用再拼命，靠的是更对的工具。\n"
    "       After：你可以收工了。\n"
    "       Bridge：从今天开始，让 {product_name} 成为那道桥。\n"
    "（屏幕角标“演绎，效果因业务场景而异”）"
)

_PAS_BAB = FormulaDefinition(
    id="pas_bab",
    name="PAS / BAB 直效响应",
    region=FormulaRegion.global_,
    category="global_direct_response",
    beats=[
        Beat(
            id="pain",
            duration_sec=10,
            function="开场即痛点：让目标受众在 2 秒内识别‘这是我的问题’",
            shot_type="close_up",
            recommended_camera_movement="static",
        ),
        Beat(
            id="agitate",
            duration_sec=10,
            function="放大痛点频次与代价，触发损失厌恶（Before 状态）",
            shot_type="medium_shot",
            recommended_camera_movement="dolly_in",
        ),
        Beat(
            id="solution_bridge",
            duration_sec=15,
            function="产品作为‘桥’把 Before 切换到 After，给出明确 CTA",
            shot_type="hand_object_face",
            recommended_camera_movement="dolly_in",
        ),
    ],
    total_shots_range=(2, 4),
    duration_sec_range=(30, 45),
    risk_flags=["unverifiable_outcome"],
    sample_dialog=_PAS_BAB_DIALOG,
    typical_duration_sec=35,
    typical_shot_count=3,
    psychology=(
        "PAS（Pain-Agitate-Solution）与 BAB（Before-After-Bridge）是直效"
        "响应文案的两大经典骨架，本质上是同一条认知路径：先放大现状的"
        "痛苦差，再呈现产品跨越差值的桥梁。它依赖损失厌恶（Kahneman &"
        " Tversky）——人为‘避免失去’付出的努力，平均是‘获得同等价值’"
        "的两倍。因此 PAS-BAB 在限时促销、转化落地页、短直效广告中表现"
        "极佳；但它会过度刺激焦虑情绪，长期使用会损害品牌资产，不适合"
        "品牌建设阶段。"
    ),
    use_cases=[
        "直效响应广告（信息流、短视频前贴片）",
        "转化落地页 / 短电商投放",
        "限时促销 / 秒杀活动",
        "A/B 测试中的‘强刺激’变体",
        "售前漏斗顶部的引流内容",
    ],
    avoid_cases=[
        "品牌建设期内容（长期使用会让用户疲劳）",
        "高端品牌（焦虑营销与品牌调性冲突）",
        "健康 / 医疗 / 情感等高敏感品类（放大痛苦易触红线）",
        "强调‘理性决策’的 B2B（叙事过于煽情）",
    ],
    sort_order=120,
)


#: 全量内置公式定义，顺序即 ``sort_order`` 升序：
#: 1. underdog_triumph（凡人逆袭，cn）
#: 2. contrast_surprise（对比反转，cn）
#: 3. workplace_hero（职场逆袭，cn）
#: 4. family_conflict（家庭冲突·高风险，cn）
#: 5. mystery_twist（悬疑反转，cn）
#: 6. time_travel（时空穿越，cn）
#: 7. heros_journey（英雄之旅，global）
#: 8. pixar_story_spine（Pixar 故事脊柱，global）
#: 9. three_act（三幕结构，global）
#: 10. scqa（SCQA 商务叙事，global）
#: 11. storybrand_sb7（StoryBrand SB7，global）
#: 12. pas_bab（PAS/BAB 直效响应，global）
BUILTIN_FORMULA_DEFINITIONS: list[FormulaDefinition] = [
    _UNDERDOG_TRIUMPH,
    _CONTRAST_SURPRISE,
    _WORKPLACE_HERO,
    _FAMILY_CONFLICT,
    _MYSTERY_TWIST,
    _TIME_TRAVEL,
    _HEROS_JOURNEY,
    _PIXAR_STORY_SPINE,
    _THREE_ACT,
    _SCQA,
    _STORYBRAND_SB7,
    _PAS_BAB,
]


# ---------------------------------------------------------------------------
# 幂等加载器
# ---------------------------------------------------------------------------


def _definition_to_orm_kwargs(definition: FormulaDefinition) -> dict[str, Any]:
    """把 :class:`FormulaDefinition` 转成 :class:`StoryFormula` 的字段字典。

    单独抽函数便于：
    - 在 INSERT 与 UPDATE 路径上复用同一份字段映射；
    - 在 ``_diff_orm_against_payload`` 中用同一组字段集判断是否变更。
    """
    return {
        "id": definition.id,
        "name": definition.name,
        "region": definition.region,
        "category": definition.category,
        "structure": definition.to_structure_payload(),
        "risk_flags": list(definition.risk_flags),
        "sample_dialog": definition.sample_dialog,
        "typical_duration_sec": definition.typical_duration_sec,
        "typical_shot_count": definition.typical_shot_count,
        "psychology": definition.psychology,
        "use_cases": list(definition.use_cases),
        "avoid_cases": list(definition.avoid_cases),
        "prompt_template_id": definition.prompt_template_id,
        "is_system": definition.is_system,
        "sort_order": definition.sort_order,
    }


def _diff_orm_against_payload(
    existing: StoryFormula, payload: dict[str, Any]
) -> bool:
    """判断已有 ORM 行是否与目标字段一致。

    返回 ``True`` 表示存在差异，需要 UPDATE；返回 ``False`` 表示已经一致，
    可计入 ``unchanged``。

    ``region`` 字段在 ORM 上是 ``FormulaRegion`` 枚举，而 payload 也是
    枚举对象，可直接比较；其它 JSON 字段比较使用 Python 等值即可（dict
    与 list 都是按值比较）。
    """
    for key, expected in payload.items():
        if key == "id":
            # ID 用作匹配键，无需 diff。
            continue
        actual = getattr(existing, key)
        # FormulaRegion 枚举与字符串值容错比较，防止从 DB 读出来的是 raw string。
        if isinstance(expected, FormulaRegion) and isinstance(actual, str):
            if actual != expected.value:
                return True
            continue
        if actual != expected:
            return True
    return False


async def bootstrap_builtin_story_formulas(
    db: AsyncSession,
) -> dict[str, int]:
    """启动时调用，幂等地确保 12 条系统级公式存在于 ``story_formulas`` 表中。

    数据来自 :data:`BUILTIN_FORMULA_DEFINITIONS`：

    - 6 条 ``region=cn`` 中国市场爆款公式（W3-T2 P1 阶段引入）；
    - 6 条 ``region=global_`` 国际经典叙事公式（W11-T1 P2 阶段引入）。

    幂等策略：
    - 以 ``StoryFormula.id`` 作为业务键。
    - 不存在则 INSERT；
    - 存在但字段集与定义不一致则按定义 UPDATE（系统级模板每次启动都对齐，
      避免运营手动改库后被遗忘）；
    - 完全一致则跳过。

    运行前置条件：``prompt_templates`` 中必须存在 id 为
    :data:`BUILTIN_FORMULA_PROMPT_TEMPLATE_ID` 的记录（由
    ``bootstrap_builtin_prompts`` 在更早阶段写入）。本函数不做该模板的
    存在性校验：让数据库 FK 约束在缺失时直接报错，便于尽早暴露启动顺序
    错误而不是事后调试。

    Args:
        db: 异步数据库会话。函数内部会执行一次 ``commit()``，因此调用方
            不需要再外层包裹事务。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}``，N+M+K 等于
        :data:`BUILTIN_FORMULA_DEFINITIONS` 的长度（当前为 12）。
    """
    counters: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}

    for definition in BUILTIN_FORMULA_DEFINITIONS:
        payload = _definition_to_orm_kwargs(definition)
        existing = await db.get(StoryFormula, definition.id)

        if existing is None:
            db.add(StoryFormula(**payload))
            counters["inserted"] += 1
            continue

        if _diff_orm_against_payload(existing, payload):
            for key, value in payload.items():
                if key == "id":
                    continue
                setattr(existing, key, value)
            counters["updated"] += 1
        else:
            counters["unchanged"] += 1

    await db.commit()
    return counters


__all__ = [
    "Beat",
    "FormulaDefinition",
    "BUILTIN_FORMULA_DEFINITIONS",
    "BUILTIN_FORMULA_PROMPT_TEMPLATE_ID",
    "KNOWN_RISK_FLAGS",
    "bootstrap_builtin_story_formulas",
]
