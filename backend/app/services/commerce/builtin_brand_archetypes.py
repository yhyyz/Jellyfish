"""系统级品牌人格原型（BrandArchetype）种子数据加载器（W11-T2，P2 准备阶段）。

本模块提供两个东西：

1. ``BUILTIN_BRAND_ARCHETYPE_DEFINITIONS``：12 条与 tonethief 词汇表对齐的
   品牌人格原型定义（``sage`` / ``jester`` / ``rebel`` / ``provocateur`` /
   ``maverick`` / ``friend`` / ``expert`` / ``cheerleader`` /
   ``storyteller`` / ``analyst`` / ``coach`` / ``minimalist``）。
2. ``bootstrap_builtin_brand_archetypes(db)``：启动时调用的幂等加载函数，
   把 12 条定义同步到 ``brand_archetypes`` 表（INSERT/UPDATE/UNCHANGED
   三态计数，``is_system=True``）。

设计原则与边界：

- 表行的 ``id`` 字段同时作为 :class:`app.models.types.BrandArchetype`
  枚举值的稳定 business key。本模块在 :data:`KNOWN_ARCHETYPE_IDS` 中保留
  一份内置词汇表副本，做"自我封闭校验"——避免 W11-T3 枚举落地时机不
  确定带来的循环依赖；运行时也会做一层断言校验（见下文 TODO）；
- ``voice_traits`` 至少 5 个、``speech_patterns`` 至少 do/don't 各 5 条、
  ``sample_brands`` 3-5 条；约束在 Pydantic 字段层强制；
- 与 :mod:`builtin_hook_patterns` / :mod:`builtin_cta_patterns` 同构：
  Pydantic 类型化 + INSERT/UPDATE/UNCHANGED 三态计数。

TODO（W13/W14）：当 W11-T3 的 ``BrandArchetype`` 枚举正式落地后，
本文件可以把 :data:`KNOWN_ARCHETYPE_IDS` 替换为
``frozenset({a.value for a in BrandArchetype})``，把 enum 来源从内置副本
切换到枚举单一真源。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_archetype import BrandArchetype


# ---------------------------------------------------------------------------
# 原型 ID 词汇表
# ---------------------------------------------------------------------------

#: 全量已知的品牌原型 ID。与 W11-T3 中的 ``BrandArchetype`` 枚举值一一对应。
#: 本模块保留独立副本以避免对 W11-T3 落地时间的强依赖，校验逻辑见
#: :class:`BrandArchetypeDefinition._validate_id`。
KNOWN_ARCHETYPE_IDS: frozenset[str] = frozenset(
    {
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
)


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


class BrandArchetypeDefinition(BaseModel):
    """单条系统级品牌人格原型定义。

    字段与 :class:`app.models.brand_archetype.BrandArchetype` 一一对齐，
    便于 bootstrap 直接映射 ORM 字段。``id`` 必须命中
    :data:`KNOWN_ARCHETYPE_IDS`，``voice_traits`` / ``sample_brands`` /
    ``speech_patterns.do/dont`` 均有最小数量约束以保证产品端"内容够丰满"。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    name_zh: str = Field(..., min_length=1, max_length=64)
    motivation: str = Field(..., min_length=1)
    voice_traits: list[str] = Field(..., min_length=5, max_length=10)
    speech_patterns: dict[str, list[str]] = Field(...)
    sample_brands: list[str] = Field(..., min_length=3, max_length=5)
    is_system: bool = True
    sort_order: int = Field(..., ge=0)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        """约束 ``id`` 仅允许 :data:`KNOWN_ARCHETYPE_IDS` 成员。

        早失败：定义阶段就拦截拼写漂移，避免错误数据进库后才被发现。
        """
        if value not in KNOWN_ARCHETYPE_IDS:
            raise ValueError(
                f"unknown archetype id {value!r}; "
                f"allowed: {sorted(KNOWN_ARCHETYPE_IDS)}"
            )
        return value

    @field_validator("speech_patterns")
    @classmethod
    def _validate_speech_patterns(
        cls, value: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """约束 ``speech_patterns`` 形如 ``{"do": [...], "dont": [...]}``。

        - 必须同时包含 ``do`` 与 ``dont`` 键（不允许漏其一）；
        - ``do`` 与 ``dont`` 至少各 5 条短句；
        - 不允许出现额外键，避免词汇漂移。
        """
        if set(value.keys()) != {"do", "dont"}:
            raise ValueError(
                "speech_patterns must have exactly keys {'do', 'dont'}, "
                f"got {sorted(value.keys())}"
            )
        for key in ("do", "dont"):
            if len(value[key]) < 5:
                raise ValueError(
                    f"speech_patterns.{key} must contain >= 5 entries; "
                    f"got {len(value[key])}"
                )
        return value


# ---------------------------------------------------------------------------
# 12 条系统级品牌人格原型（按 sort_order 升序）
# ---------------------------------------------------------------------------


_SAGE = BrandArchetypeDefinition(
    id="sage",
    name="Sage",
    name_zh="智者",
    motivation=(
        "智者原型的核心动机是“通过知识与洞察让世界更清晰”。它相信真理可"
        "以被理解、被传递、被产品化，沟通时强调“我们已经把复杂问题想透了"
        "，你只需要相信我们的判断“。智者品牌避免低级娱乐与情绪煽动，倾向"
        "于用专业语言与温和权威建立信任。它适合知识密集型产品（金融、教"
        "育、咨询、专业工具），但容易因为过度严肃而与年轻人群产生距离感"
        "，需要在文案中加入“对人类好奇心的温柔回应”。"
    ),
    voice_traits=[
        "权威而非高傲",
        "克制",
        "理性",
        "深思熟虑",
        "温和",
        "精确",
        "可被验证",
    ],
    speech_patterns={
        "do": [
            "用陈述句给出结论",
            "引用第一性原理或长期数据",
            "承认复杂性而不简化它",
            "用具体术语而非“很多人”",
            "邀请观众“再想一遍”",
        ],
        "dont": [
            "使用网络梗或流行语",
            "用感叹号堆叠情绪",
            "做“煽动式”“标题党”",
            "对竞品进行情绪化批判",
            "用模糊形容词（“超棒”“绝了”）",
        ],
    },
    sample_brands=["Apple", "IBM", "The Economist", "Lexus"],
    sort_order=10,
)


_JESTER = BrandArchetypeDefinition(
    id="jester",
    name="Jester",
    name_zh="小丑",
    motivation=(
        "小丑原型的核心动机是“用幽默让生活变得更轻松”。它通过自嘲、反差、"
        "意外结构让消费者笑出声，并在笑声中记住品牌。小丑品牌不是肤浅，"
        "而是“故意用轻盈的方式说严肃的话”。它适合日常消费品、生活方式品、"
        "餐饮饮料这类需要被反复消费的品类——因为幽默感天然带来传播力与"
        "复购意愿。但它的边界在于不能用幽默掩饰功能性沟通的缺失，否则会"
        "演变成“光好笑但不知道在卖什么”。"
    ),
    voice_traits=[
        "顽皮",
        "自嘲",
        "反差感",
        "节奏明快",
        "亲和",
        "记忆点强",
        "敢自黑",
    ],
    speech_patterns={
        "do": [
            "用反差/双关/谐音作为开场",
            "把缺点变成笑点",
            "用拟人化对话",
            "短句叠加节奏感",
            "在结尾留一个“自我嘲笑”出口",
        ],
        "dont": [
            "嘲笑用户的痛点",
            "把幽默建立在地域/性别/职业刻板印象上",
            "全程笑而不卖产品",
            "用过时的网络梗（瞬间老化）",
            "把品牌做成无差别段子手",
        ],
    },
    sample_brands=["Old Spice", "M&Ms", "Dollar Shave Club", "Skittles"],
    sort_order=20,
)


_REBEL = BrandArchetypeDefinition(
    id="rebel",
    name="Rebel",
    name_zh="反叛者",
    motivation=(
        "反叛者原型的核心动机是“打破规则、挑战现状、为不被主流理解的人发"
        "声“。它把品牌姿态站在”建制“的对立面：当主流说要”克制“，反叛者"
        "说要“放肆”；当主流说要“妥协”，反叛者说要“坚持”。它的品牌价值"
        "来源于对小众价值观的高度忠诚——你必须知道你不是为所有人服务的，"
        "并把这一点写在品牌的每一句文案里。反叛者品牌特别适合年轻、亚文"
        "化、户外、烈酒、机车这些品类。"
    ),
    voice_traits=[
        "锋利",
        "桀骜",
        "立场鲜明",
        "拒绝讨好",
        "粗粝",
        "敢说",
        "充满能量",
    ],
    speech_patterns={
        "do": [
            "用否定句开头（“不要再被告诉……”）",
            "宣示立场，承担代价",
            "用“我们 vs 他们”二元结构",
            "拒绝糖衣，直接说出难听话",
            "强调代际/世代差异",
        ],
        "dont": [
            "用乖巧的礼貌用语",
            "对所有人说“我们都喜欢你”",
            "讨好平台或主流意见",
            "用万年不变的成功学口吻",
            "对小众群体使用居高临下的姿态",
        ],
    },
    sample_brands=["Harley-Davidson", "Diesel", "Vans", "Doc Martens"],
    sort_order=30,
)


_PROVOCATEUR = BrandArchetypeDefinition(
    id="provocateur",
    name="Provocateur",
    name_zh="挑衅者",
    motivation=(
        "挑衅者原型的核心动机是“用争议唤起注意，用反共识让人停下来重新看"
        "一眼“。挑衅者比反叛者更激进——反叛者只是”不站主流“，挑衅者会"
        "主动制造话题。它通过反向命题、视觉冲击、价值观对峙让品牌成为"
        "新闻本身。但它也是 12 个原型里风险最高的：尺度一旦失手，就会从"
        "“被讨论”变成“被抵制”。一个挑衅者品牌必须在内部建立“红线清单”，"
        "并保有对失败叙事的快速止损能力。"
    ),
    voice_traits=[
        "尖锐",
        "戏剧化",
        "放大",
        "对峙",
        "情绪化但克制",
        "敢出格",
        "愿承担争议",
    ],
    speech_patterns={
        "do": [
            "用反向命题（“不是 X，而是 Y”）",
            "把对立面放在画面里",
            "敢做视觉性的不舒适",
            "用一句话概括立场",
            "拒绝“两边都说一点”的折中",
        ],
        "dont": [
            "把挑衅与冒犯混为一谈",
            "用受害者身份做营销",
            "把政治/民族/宗教作为挑衅工具",
            "为了流量牺牲品牌长期资产",
            "在大型敏感事件上抢热度",
        ],
    },
    sample_brands=["Liquid Death", "Tesla", "Diesel"],
    sort_order=40,
)


_MAVERICK = BrandArchetypeDefinition(
    id="maverick",
    name="Maverick",
    name_zh="独行者",
    motivation=(
        "独行者原型的核心动机是“按自己的节奏走，不为外部的喧嚣调整方向”。"
        "独行者不像反叛者那样高声反对，也不像挑衅者那样制造话题——它只是"
        "“不参与”。独行者品牌往往生长在户外、环保、独立创作、慢生活、专"
        "业小众品类，它的传播力来自“令人尊敬的孤独”。它鼓励用户“做自己”，"
        "并把产品本身作为这种生活方式的工具，而不是宣讲对象。"
    ),
    voice_traits=[
        "沉静",
        "笃定",
        "专注",
        "不解释",
        "诚实",
        "独立",
        "克制",
    ],
    speech_patterns={
        "do": [
            "用第一人称叙述选择",
            "强调“为什么我们做”而非“为什么你应该买”",
            "用长曝光的画面与简短句子",
            "承认自己不为所有人服务",
            "把环境/自然/工艺作为主角",
        ],
        "dont": [
            "频繁追热点",
            "用“全网爆款”标签",
            "在文案里强调“潮流”",
            "迎合短视频常见模板",
            "用 KOL 横扫式投放",
        ],
    },
    sample_brands=["Patagonia", "Filson", "REI", "Yeti"],
    sort_order=50,
)


_FRIEND = BrandArchetypeDefinition(
    id="friend",
    name="Friend",
    name_zh="朋友",
    motivation=(
        "朋友原型的核心动机是“陪伴、温暖、让人觉得被看见”。它不试图比观"
        "众更聪明、更高级、更酷，而是“和你站在一起”。朋友品牌喜欢用第二"
        "人称、用日常场景、用熟悉的口吻交流——咖啡、家居、日用消费品、社"
        "交平台都很适合朋友原型。它的最大风险是边界不清：什么都想说、什"
        "么都参与，最终丢失独特性。所以“朋友”必须想清楚自己是哪一种朋"
        "友（懂吃的朋友？爱旅行的朋友？爱学习的朋友？）。"
    ),
    voice_traits=[
        "亲切",
        "温暖",
        "包容",
        "口语化",
        "贴心",
        "可信",
        "陪伴感",
    ],
    speech_patterns={
        "do": [
            "用第二人称“你”",
            "讲熟人之间会讲的小细节",
            "把场景做日常化",
            "在结尾留一句“我也是这么过来的”",
            "用问候式开场（“忙了一天，回家了吗？”）",
        ],
        "dont": [
            "在朋友面前装权威",
            "用“科普口吻”压制对话感",
            "频繁推销而忽略关心",
            "用过度礼貌掩盖真实表达",
            "对用户的处境视而不见",
        ],
    },
    sample_brands=["Coca-Cola", "Visa", "Starbucks", "IKEA"],
    sort_order=60,
)


_EXPERT = BrandArchetypeDefinition(
    id="expert",
    name="Expert",
    name_zh="专家",
    motivation=(
        "专家原型的核心动机是“通过专业能力让事情被做对”。它和智者的差别"
        "在于：智者关心“理解”，专家关心“执行”。专家品牌会反复展示工艺、"
        "参数、流程、复杂度，让消费者感受到“这是一群真正懂的人”。专家原"
        "型适合 3C、医美、精密器械、专业工具、咨询服务等品类，它对内容"
        "颗粒度的要求很高——任何一处细节漂移都会损伤整体专业感。"
    ),
    voice_traits=[
        "严谨",
        "技术性",
        "数据驱动",
        "不掺水",
        "克制",
        "条理清晰",
        "高密度",
    ],
    speech_patterns={
        "do": [
            "用具体参数代替“很好”",
            "解释工艺/材料/流程的取舍",
            "承认局限",
            "对术语保持稳定一致",
            "用“工程师视角”讲故事",
        ],
        "dont": [
            "用情绪型形容词",
            "为了好看简化关键参数",
            "用对手不专业反衬自己",
            "回避边界条件（“什么时候不适用”）",
            "把数据装饰成“卖点话术”",
        ],
    },
    sample_brands=["Bose", "DJI", "Bosch", "Lexus"],
    sort_order=70,
)


_CHEERLEADER = BrandArchetypeDefinition(
    id="cheerleader",
    name="Cheerleader",
    name_zh="鼓励者",
    motivation=(
        "鼓励者原型的核心动机是“让人相信自己可以”。它把品牌站在用户身边"
        "做正向放大器——鼓掌、加油、击掌、拥抱。鼓励者并不掩盖现实的难，"
        "而是承认“难”之后说“你能做到”。它特别适合运动、健身、教育、个人"
        "成长这类需要长期坚持的品类。鼓励者最常见的失败模式是“廉价鸡汤”"
        "——空洞的“加油”反而让用户觉得品牌不懂自己，所以鼓励必须被钉在"
        "一个具体的小目标上。"
    ),
    voice_traits=[
        "积极",
        "热血",
        "韧性",
        "有节奏感",
        "鼓舞",
        "真诚",
        "笃定",
    ],
    speech_patterns={
        "do": [
            "用“你”做主语，把成功分给用户",
            "承认难，再给到行动建议",
            "用动词驱动文案（动起来 / 走出去）",
            "在结尾留一个具体的下一步",
            "庆祝小成就",
        ],
        "dont": [
            "用空洞的鸡汤词（“相信自己”“万事可期”）",
            "回避用户真实困难",
            "把品牌塑造成“不停打鸡血”",
            "对失败一字不提",
            "用焦虑驱动转化（“再不做就晚了”）",
        ],
    },
    sample_brands=["Nike", "Under Armour", "Peloton", "Adidas"],
    sort_order=80,
)


_STORYTELLER = BrandArchetypeDefinition(
    id="storyteller",
    name="Storyteller",
    name_zh="说书人",
    motivation=(
        "说书人原型的核心动机是“用故事让世界变得更值得活”。它不直接讲产"
        "品参数，而是把产品放进一个有人物、有情节、有冲突、有变化的世"
        "界。说书人品牌相信“被记住的不是事实，而是叙事”。它特别适合内"
        "容平台、儿童娱乐、文创、旅行、酒类等需要长期文化资产沉淀的品"
        "类。说书人最大的风险是叙事过度——故事漂亮但消费者忘了买什么。"
    ),
    voice_traits=[
        "叙事性",
        "想象力",
        "节奏",
        "细节感",
        "情感曲线",
        "充满意象",
        "温柔",
    ],
    speech_patterns={
        "do": [
            "以人物或场景开场",
            "用“那一年”“有一次”建立时间感",
            "在结尾留出余韵",
            "把产品塞进故事而非倒过来",
            "用具体细节代替形容词",
        ],
        "dont": [
            "强行抒情",
            "为了煽情扭曲事实",
            "把每个产品都做成史诗",
            "用模板化“励志故事”",
            "结尾突兀转向硬广",
        ],
    },
    sample_brands=["Disney", "Airbnb", "Hennessy", "Lego"],
    sort_order=90,
)


_ANALYST = BrandArchetypeDefinition(
    id="analyst",
    name="Analyst",
    name_zh="分析师",
    motivation=(
        "分析师原型的核心动机是“用数据与结构让混沌变得可被理解”。它和专"
        "家的差别在于：专家解决具体执行，分析师解决决策选择。分析师品"
        "牌喜欢列表、对比、矩阵、原始数据、引用源。它特别适合 B2B SaaS、"
        "金融服务、咨询机构、行业研究等领域。分析师品牌的失败模式是"
        "“信息过载”——太多数据反而让消费者放弃，所以必须有清晰的层级与"
        "结论先行的结构。"
    ),
    voice_traits=[
        "结构化",
        "数据驱动",
        "克制",
        "理性",
        "条理清晰",
        "不夸张",
        "可被引用",
    ],
    speech_patterns={
        "do": [
            "结论先行，再给依据",
            "用图表/对比/矩阵",
            "明确数据来源与时间窗",
            "区分事实与解释",
            "在结尾给“决策建议”而非“喊口号”",
        ],
        "dont": [
            "用情绪化形容词",
            "省略关键样本说明",
            "数据装饰化",
            "断章取义引用研究",
            "强行把复杂结论简化成单句口号",
        ],
    },
    sample_brands=["McKinsey", "Goldman Sachs", "Bloomberg", "Gartner"],
    sort_order=100,
)


_COACH = BrandArchetypeDefinition(
    id="coach",
    name="Coach",
    name_zh="教练",
    motivation=(
        "教练原型的核心动机是“把模糊的目标变成可执行的训练计划”。教练比"
        "鼓励者更具方法论：它不只是说“你能做到”，而是说“今天先做这 3 件"
        "事“。教练品牌喜欢量化、阶段化、拆解、复盘。它特别适合健身、学"
        "习、效率工具、个人成长、技能培训等品类。教练原型的失败模式是"
        "“说教感过重”——过度强调“必须”“应该”会让用户感到压力，所以教练"
        "需要在“指导”与“陪伴”之间找到平衡。"
    ),
    voice_traits=[
        "有方法",
        "结构化",
        "鼓舞但务实",
        "节奏感",
        "可执行",
        "诚实",
        "陪伴感",
    ],
    speech_patterns={
        "do": [
            "用“今天先做……”开启行动",
            "把目标拆为阶段",
            "提供反馈机制",
            "承认失败也是数据",
            "用“我们”建立同盟感",
        ],
        "dont": [
            "用居高临下的“必须”“应该”",
            "只讲理论不给步骤",
            "把训练做成羞耻感来源",
            "对所有用户用同一个计划",
            "忽视用户的实际起点",
        ],
    },
    sample_brands=["Under Armour", "Peloton", "Coursera", "MasterClass"],
    sort_order=110,
)


_MINIMALIST = BrandArchetypeDefinition(
    id="minimalist",
    name="Minimalist",
    name_zh="极简主义者",
    motivation=(
        "极简主义者原型的核心动机是“用更少做更好”。它相信噪声是品牌最大"
        "的敌人——产品越少越精，文案越短越准，画面越白越静。极简主义者"
        "品牌通过克制建立辨识度——当所有人都在堆叠卖点，极简主义者只说"
        "一句。它特别适合家居、文具、生活方式、一些科技品类。最大风险"
        "是“克制变成空洞”——极简不是少说话，而是把每一句都磨到刚刚好。"
    ),
    voice_traits=[
        "克制",
        "精确",
        "留白",
        "纯粹",
        "稳定",
        "去装饰",
        "理性美感",
    ],
    speech_patterns={
        "do": [
            "用单一概念贯穿全篇",
            "每一句尽量是“一句话能说清”",
            "把多余的形容词删掉",
            "用结构与节奏替代修辞",
            "让画面与产品自身说话",
        ],
        "dont": [
            "堆叠卖点",
            "用密集的促销字幕",
            "做“全网最便宜”式喊麦",
            "把克制做成“冷漠”",
            "用复杂术语炫技",
        ],
    },
    sample_brands=["Muji", "Apple", "Aesop", "Uniqlo"],
    sort_order=120,
)


#: 全量内置原型定义，顺序即 ``sort_order`` 升序：
#: 1. sage（智者）
#: 2. jester（小丑）
#: 3. rebel（反叛者）
#: 4. provocateur（挑衅者）
#: 5. maverick（独行者）
#: 6. friend（朋友）
#: 7. expert（专家）
#: 8. cheerleader（鼓励者）
#: 9. storyteller（说书人）
#: 10. analyst（分析师）
#: 11. coach（教练）
#: 12. minimalist（极简主义者）
BUILTIN_BRAND_ARCHETYPE_DEFINITIONS: list[BrandArchetypeDefinition] = [
    _SAGE,
    _JESTER,
    _REBEL,
    _PROVOCATEUR,
    _MAVERICK,
    _FRIEND,
    _EXPERT,
    _CHEERLEADER,
    _STORYTELLER,
    _ANALYST,
    _COACH,
    _MINIMALIST,
]


# ---------------------------------------------------------------------------
# 幂等加载器
# ---------------------------------------------------------------------------


def _definition_to_orm_kwargs(
    definition: BrandArchetypeDefinition,
) -> dict[str, Any]:
    """把 :class:`BrandArchetypeDefinition` 转成 :class:`BrandArchetype` 字段字典。"""
    return {
        "id": definition.id,
        "name": definition.name,
        "name_zh": definition.name_zh,
        "motivation": definition.motivation,
        "voice_traits": list(definition.voice_traits),
        # speech_patterns 是 dict，重建一份新对象避免共享引用。
        "speech_patterns": {
            "do": list(definition.speech_patterns["do"]),
            "dont": list(definition.speech_patterns["dont"]),
        },
        "sample_brands": list(definition.sample_brands),
        "is_system": definition.is_system,
        "sort_order": definition.sort_order,
    }


def _diff_orm_against_payload(
    existing: BrandArchetype, payload: dict[str, Any]
) -> bool:
    """判断 ORM 行是否与目标字段一致；返回 ``True`` 即需要 UPDATE。"""
    for key, expected in payload.items():
        if key == "id":
            continue
        if getattr(existing, key) != expected:
            return True
    return False


async def bootstrap_builtin_brand_archetypes(
    db: AsyncSession,
) -> dict[str, int]:
    """启动时调用，幂等地确保 12 条内置品牌人格原型存在于 ``brand_archetypes`` 表中。

    幂等策略与 :func:`bootstrap_builtin_hook_patterns` 一致：以
    ``BrandArchetype.id`` 为业务键，INSERT/UPDATE/UNCHANGED 三态计数。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}``，三者之和等于
        :data:`BUILTIN_BRAND_ARCHETYPE_DEFINITIONS` 的长度（当前为 12）。
    """
    counters: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}

    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        payload = _definition_to_orm_kwargs(definition)
        existing = await db.get(BrandArchetype, definition.id)

        if existing is None:
            db.add(BrandArchetype(**payload))
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
    "BrandArchetypeDefinition",
    "BUILTIN_BRAND_ARCHETYPE_DEFINITIONS",
    "KNOWN_ARCHETYPE_IDS",
    "bootstrap_builtin_brand_archetypes",
]
