"""系统级剧情公式（StoryFormula）种子数据加载器（W3-T2，P1 阶段）。

本模块提供两个东西：

1. ``BUILTIN_FORMULA_DEFINITIONS``：一个类型化、可在测试与 UI 复用的 6 条
   中国市场爆款公式注册表（``underdog_triumph`` / ``contrast_surprise`` /
   ``workplace_hero`` / ``family_conflict`` / ``mystery_twist`` /
   ``time_travel``）。
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


#: 全量内置公式定义，顺序即 ``sort_order`` 升序：
#: 1. underdog_triumph（凡人逆袭）
#: 2. contrast_surprise（对比反转）
#: 3. workplace_hero（职场逆袭）
#: 4. family_conflict（家庭冲突·高风险）
#: 5. mystery_twist（悬疑反转）
#: 6. time_travel（时空穿越）
BUILTIN_FORMULA_DEFINITIONS: list[FormulaDefinition] = [
    _UNDERDOG_TRIUMPH,
    _CONTRAST_SURPRISE,
    _WORKPLACE_HERO,
    _FAMILY_CONFLICT,
    _MYSTERY_TWIST,
    _TIME_TRAVEL,
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
    """启动时调用，幂等地确保 6 条中国爆款公式存在于 ``story_formulas`` 表中。

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
        :data:`BUILTIN_FORMULA_DEFINITIONS` 的长度（当前为 6）。
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
