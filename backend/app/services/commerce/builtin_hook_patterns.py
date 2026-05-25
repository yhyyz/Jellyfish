"""系统级钩子模式（HookPattern）种子数据加载器（W11-T2，P2 准备阶段）。

本模块提供两个东西：

1. ``BUILTIN_HOOK_PATTERN_DEFINITIONS``：一个类型化、可在测试与 UI 复用的
   10 条钩子模式定义（``question_hook`` / ``conflict_hook`` /
   ``contrast_hook`` / ``numerical_hook`` / ``curiosity_hook`` /
   ``shock_hook`` / ``relatable_hook`` / ``dialogue_hook`` /
   ``visual_hook`` / ``pov_hook``）。
2. ``bootstrap_builtin_hook_patterns(db)``：启动时调用的幂等加载函数，
   把上述定义同步到 ``hook_patterns`` 表（INSERT/UPDATE/UNCHANGED 三态
   计数，``is_system=True``）。

设计原则与边界：

- 钩子模式属于 P2 钩子工作流（Wave 13/14）的"产品级运营资产"，与
  :mod:`app.services.commerce.builtin_story_formulas` 同构 —— 但故意不
  共享 :data:`KNOWN_PATTERN_TYPES` 与公式风险词汇表，避免不同子系统的
  vocabulary 互相污染；
- ``template_text`` 是 Jinja2 模板片段，本期仅落库；具体渲染契约由 Wave
  13 的钩子工作流定义；
- ``pattern_type`` 是稳定词汇表 :data:`KNOWN_PATTERN_TYPES` 的成员，新增
  类型必须扩 vocabulary 并同步到前端筛选与文档；
- 不在本期与 ``StoryVariant.hook_pattern_id`` 建立硬外键，留给 P2 集成
  阶段决定 ``ON DELETE`` 策略。

为什么单独引入 :class:`HookPatternDefinition`：

- 直接维护 dict 列表会缺失类型校验，``use_cases`` / ``avoid_cases`` /
  ``pattern_type`` 在 review 时极易写错；
- 用 Pydantic v2 ``BaseModel`` + ``ConfigDict(extra="forbid")`` 把 10 条
  钩子当成"结构化配置"治理，能在测试与启动时第一时间拦截字段拼写错
  误，与 :class:`FormulaDefinition` 的治理思路一致。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hook_pattern import HookPattern


# ---------------------------------------------------------------------------
# 钩子类型词汇表
# ---------------------------------------------------------------------------

#: 全量已知的钩子类型，``HookPatternDefinition.pattern_type`` 必须命中此集合。
#: 任何扩展必须同步到前端筛选下拉、运营文档与 Wave 13 钩子工作流。
KNOWN_PATTERN_TYPES: frozenset[str] = frozenset(
    {
        "question",
        "conflict",
        "contrast",
        "numerical",
        "curiosity",
        "shock",
        "relatable",
        "dialogue",
        "visual",
        "pov",
    }
)


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


class HookPatternDefinition(BaseModel):
    """单条系统级钩子定义。

    字段语义与 :class:`app.models.hook_pattern.HookPattern` 严格对齐，便于
    一一映射；额外通过 :meth:`to_orm_kwargs` 在 bootstrap 中转成 ORM 字
    段字典。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    pattern_type: str = Field(..., min_length=1, max_length=32)
    description: str = Field(..., min_length=1)
    template_text: str = Field(..., min_length=1)
    psychology: str = Field(..., min_length=1)
    use_cases: list[str] = Field(..., min_length=1)
    avoid_cases: list[str] = Field(..., min_length=1)
    is_system: bool = True
    sort_order: int = Field(..., ge=0)

    @field_validator("pattern_type")
    @classmethod
    def _validate_pattern_type(cls, value: str) -> str:
        """约束 ``pattern_type`` 只允许 :data:`KNOWN_PATTERN_TYPES` 成员。"""
        if value not in KNOWN_PATTERN_TYPES:
            raise ValueError(
                f"unknown pattern_type {value!r}; "
                f"allowed: {sorted(KNOWN_PATTERN_TYPES)}"
            )
        return value


# ---------------------------------------------------------------------------
# 10 条系统级钩子（按 sort_order 升序）
# ---------------------------------------------------------------------------


_QUESTION_HOOK = HookPatternDefinition(
    id="question_hook",
    name="问句钩子",
    pattern_type="question",
    description=(
        "用一个直击痛点的问句开场，把观众从“路过状态”瞬间切换到“自我"
        "审问状态“。问句钩子的关键是问题必须够具体、够窄、够能”戳到“对应"
        "目标人群——“你也总在 21 点之后才发现今天什么都没干吗？”远比“你"
        "工作效率高吗？“更有效。问号在视觉上还会驱动观众继续往下看以"
        "等待答案，配合屏幕字幕呈现可显著提高 3 秒完播率，是中国短视频信"
        "息流环境下最稳定的流量起手式之一。"
    ),
    template_text=(
        "{{ character }}站在镜头前直视观众。\n"
        "字幕：你知道 {{ audience_pain }} 真正的原因，其实不是你想的那样吗？\n"
        "（停顿 0.3s 后）然后我才明白：原来差的不是我，是 {{ product_name }}。"
    ),
    psychology=(
        "认知关闭需求（Need for Cognitive Closure）+ 自我相关性效应：人脑"
        "对未解之问会自动维持注意力直到得到答案，问句越具体目标受众越容"
        "易投射自我，进而把停留转化为完播。"
    ),
    use_cases=[
        "目标人群高度具体（年龄/职业/性别可命中）",
        "产品解决一个清晰的痛点",
        "信息流投放（标题与首帧字幕需对齐）",
        "教育/学习/职场效率类内容",
    ],
    avoid_cases=[
        "问题过于宽泛（“你想成功吗？”）",
        "答案显而易见（让观众觉得被低估）",
        "敏感话题做诱导式提问（涉医/涉政/涉敏感人群）",
    ],
    sort_order=10,
)


_CONFLICT_HOOK = HookPatternDefinition(
    id="conflict_hook",
    name="冲突钩子",
    pattern_type="conflict",
    description=(
        "用两个角色在镜头开场即处于明显对立状态来制造张力——同事 vs "
        "新人、婆婆 vs 儿媳、老板 vs 员工、伴侣之间。冲突钩子的核心不是"
        "撕裂，而是给观众一个“我必须看到结局”的承诺：观众会想知道这场冲"
        "突如何收场。短视频信息流里，前 1 秒的对立面孔比慢热铺陈更能"
        "立刻钉住注意力，但务必把对立做成可调和的“误解”或“立场差异”，"
        "避免演变成人身攻击或地域/性别对立。"
    ),
    template_text=(
        "（开场画面：两人并立，表情对立）\n"
        "{{ rival }}：你这种 {{ negative_label }}，凭什么能 {{ aspiration }}？\n"
        "{{ character }}（沉默两秒，从背后拿出 {{ product_name }}）：\n"
        "也许我本来不行——但今天不一样。"
    ),
    psychology=(
        "社会比较 + 替代性争论：观众会自动把自己代入弱势一方，期待看到反"
        "转完成情绪释放；冲突的可见性还触发短视频算法对“留存曲线急速上"
        "升“的偏好，提高初始分发。"
    ),
    use_cases=[
        "职场/家庭/校园场景的剧情带货",
        "产品具备“打脸式”功能演示空间",
        "目标人群对“被低估”有强情绪共鸣",
    ],
    avoid_cases=[
        "把家庭成员塑造成纯粹反派（限流风险）",
        "性别/地域/学历对立做戏剧化处理",
        "通过侮辱性台词制造冲突",
    ],
    sort_order=20,
)


_CONTRAST_HOOK = HookPatternDefinition(
    id="contrast_hook",
    name="对比钩子",
    pattern_type="contrast",
    description=(
        "把“使用前 vs 使用后”、“普通 vs 专业”、“昨天 vs 今天”两个状态在"
        "首帧分屏或快切呈现，观众在 1 秒内就读懂“差距”，进而想看“为什么"
        "差距如此大“。对比钩子和 :class:`underdog_triumph` 公式天然贴合，"
        "是化妆品、家电、办公工具等可见化品类的最稳定流量起手式。重点"
        "是对比要“诚实可信”——不要做极端 P 图，否则观众一旦怀疑差距是滤"
        "镜或后期，整段内容的可信度都会崩塌。"
    ),
    template_text=(
        "（首帧：分屏左右对比；左：旧状态，右：新状态）\n"
        "字幕（左）：3 个月前的我 ——\n"
        "字幕（右）：用过 {{ product_name }} 的我 ——\n"
        "（中央切到产品特写，停留 0.5s）\n"
        "字幕：差的不是天赋，是工具。"
    ),
    psychology=(
        "锚定效应 + 对比效应：人对“前后差异”的感知远强于绝对值；先把痛点"
        "状态作为锚点压低期待，再以新状态拉高，差值被情绪放大数倍。"
    ),
    use_cases=[
        "化妆/护肤/服装等可视化品类",
        "智能硬件/办公工具的效率前后对比",
        "学习类产品的成绩/状态前后对比",
    ],
    avoid_cases=[
        "极端美化（与实拍差距过大）",
        "暗示治病/医疗效果",
        "用对比贬低身材/肤色/外貌",
    ],
    sort_order=30,
)


_NUMERICAL_HOOK = HookPatternDefinition(
    id="numerical_hook",
    name="数字钩子",
    pattern_type="numerical",
    description=(
        "在第一句台词或字幕里抛出一个具体到不可质疑的数字——“3 件”、"
        "“100 个”、“7 天”、“83%”——把观众的预期锚定到一个清单结构上，"
        "迫使大脑期待“把列表看完才能闭环”。数字钩子比模糊承诺更容易"
        "通过审核，因为它本身不带绝对承诺；同时它给后续镜头分段提供了"
        "天然的节拍标尺，3 件就是 3 个镜头组，便于 LLM 生成结构化分镜。"
    ),
    template_text=(
        "（黑底白字大号字幕渐入）\n"
        "我用 {{ product_name }} 做对的 3 件事——\n"
        "（切到第 1 件操作的特写，0.6s）\n"
        "（切到第 2 件操作的特写，0.6s）\n"
        "（切到第 3 件操作的中景，1.0s）\n"
        "字幕：每一件都很小，但合在一起救了我。"
    ),
    psychology=(
        "完形闭合 + 可数性偏差：人脑天然对“清单未完成”耿耿于怀，数字越具"
        "体观众越愿意等到 N=N 才离开；“83%”这类带小数的数据也会被默认"
        "为更可信。"
    ),
    use_cases=[
        "教程/技巧/经验分享",
        "成分/卖点稠密的护肤、保健、家电类",
        "投流标题需要清晰收益感的场景",
    ],
    avoid_cases=[
        "数字不可验证（“瘦 30 斤”“日入万元”）",
        "数字与实际镜头不对齐（说 5 件只演 3 件）",
        "用 #1 / 市占第一 等行业垄断式表述（广告法红线）",
    ],
    sort_order=40,
)


_CURIOSITY_HOOK = HookPatternDefinition(
    id="curiosity_hook",
    name="好奇钩子",
    pattern_type="curiosity",
    description=(
        "在开场刻意留下一个不解释的悬念——一个被遮住的产品包装、一个"
        "未拆封的包裹、一个标题只到一半的字幕。好奇钩子靠“已知 vs 想知"
        "的缺口锁定注意力，特别适合产品本身有故事感（联名、定制、限定）"
        "或场景本身具备神秘感（深夜、独处、清晨）。它的天敌是“答非所"
        "问“——结尾必须真的兑现开场承诺，否则观众会留下”被骗“的印象，"
        "影响后续点赞与复看率。"
    ),
    template_text=(
        "（开场：一只手把 {{ product_name }} 的包装盒推进画面，但包装"
        "贴纸故意被另一只手挡住）\n"
        "画外独白：这家伙救了我整个 {{ context }}——但我先不告诉你它是什么。\n"
        "（暗切到生活场景，悬念暂留 5-8s）"
    ),
    psychology=(
        "好奇心缺口理论（Loewenstein 1994）：当人感知到“已知”和“想知”之"
        "间存在缺口，注意力被强制锁定直到缺口被填平。"
    ),
    use_cases=[
        "联名/限定/定制款产品",
        "故事感强的品牌（手作、独立设计）",
        "悬疑反转剧本搭配",
    ],
    avoid_cases=[
        "结尾兑现不足（标题党）",
        "内容本身无故事感（强行制造悬念）",
        "悬念时间过长（>10s）导致流失",
    ],
    sort_order=50,
)


_SHOCK_HOOK = HookPatternDefinition(
    id="shock_hook",
    name="震惊钩子",
    pattern_type="shock",
    description=(
        "用一个反常规、违反直觉、与日常经验冲突的画面或事实开场——"
        "“把这个倒进咖啡里”、“90% 的人都用错了它”、“我连续 30 天没洗过这"
        "个”。震惊钩子在算法上对“前 1 秒留存”几乎是必杀技，但合规"
        "成本极高：极易演变为夸大、误导或猎奇。安全做法是把“震惊”局限"
        "在“反直觉但合规的真实事实”，并立刻在第二个镜头给出温和解释，"
        "把观众从“被吓到”过渡到“被科普到”。"
    ),
    template_text=(
        "（开场：一个反常动作的特写，如把 {{ product_name }} 用在意想"
        "不到的位置）\n"
        "字幕：你没看错——这就是我每天都做的事。\n"
        "（0.8s 后切到全景，给出场景与原因）\n"
        "画外独白：很多人用错了 {{ product_name }}，所以一直没看到效果。"
    ),
    psychology=(
        "新奇度反应（novelty response）+ 期望违反（expectation violation）："
        "大脑在 100ms 内判定画面“不寻常”，自动提升注意力分配；如果在 1s "
        "内能给到合理解释，注意力会从“猎奇”转为“求知”。"
    ),
    use_cases=[
        "产品有非常规使用方式",
        "目标人群对常见误区有共识",
        "科普/知识类带货",
    ],
    avoid_cases=[
        "夸大/误导/虚假演示",
        "猎奇低俗（呕吐/血腥/虐待）",
        "震惊但与产品无关（蹭流量）",
    ],
    sort_order=60,
)


_RELATABLE_HOOK = HookPatternDefinition(
    id="relatable_hook",
    name="共鸣钩子",
    pattern_type="relatable",
    description=(
        "用一段极度生活化的、目标人群一看就知道“这就是我”的痛点场景开"
        "场——“加班到 11 点回家发现冰箱只剩半瓶水”、“开会前 5 分钟才发"
        "现 PPT 字体全乱了“。共鸣钩子不靠戏剧性赢取注意，而是靠精准的"
        "人群侧写赢取信任：当观众感觉“主角懂我”，后续产品推荐就有了情"
        "感前提。共鸣钩子的关键是细节——一个具体到“加班 11 点”的小细"
        "节比一句“我太忙了”有效十倍。"
    ),
    template_text=(
        "（开场：场景化镜头，无台词）\n"
        "字幕：又到了 {{ specific_time_or_situation }}……\n"
        "{{ character }}（疲惫地望着 {{ object_of_pain }}）：\n"
        "唉，今天又是这样。\n"
        "（暂停 0.5s，画面切到 {{ product_name }} 自然出现）"
    ),
    psychology=(
        "自我参照效应（self-reference effect）：与自我相关的信息加工更深"
        "且记忆更牢，“被理解”的感受是观众停留与点赞的核心驱动。"
    ),
    use_cases=[
        "目标人群高度集中（宝妈/打工人/学生党）",
        "产品定位“陪伴式”“日常型”",
        "品牌想建立长期信任而非单次冲动",
    ],
    avoid_cases=[
        "强行共鸣（人群侧写不准）",
        "苦情过度（让观众“看着累”）",
        "用“贬低自己”博同情",
    ],
    sort_order=70,
)


_DIALOGUE_HOOK = HookPatternDefinition(
    id="dialogue_hook",
    name="对白钩子",
    pattern_type="dialogue",
    description=(
        "用两个或多个角色在镜头开场即直接对话开场，观众像偷听一段戏一"
        "样被“代入”剧情。对白钩子比独白更有戏剧推进力，因为它天然带角"
        "色关系（同事、夫妻、母女、朋友），关系自带情感张力。它对台词"
        "的密度要求更高——前 3 秒至少要交付一个“立场”或一个“信息冲突”，"
        "否则观众会感觉“在看广告对白排练”。"
    ),
    template_text=(
        "{{ character_a }}：你最近怎么变化这么大？\n"
        "{{ character_b }}（笑而不语，从手边拿出 {{ product_name }}）：\n"
        "因为我换了它。\n"
        "{{ character_a }}（凑近看）：这个？真的有用？"
    ),
    psychology=(
        "社会临场感（social presence）：多角色对话激活观众“听到秘密”的窥"
        "私感，提高初始注意力；同时角色关系自带情感预期，观众会期待"
        "看到关系如何变化。"
    ),
    use_cases=[
        "情侣/家庭/职场场景的剧情带货",
        "产品需要靠“被推荐”建立信任的品类",
        "角色 IP 系列化内容",
    ],
    avoid_cases=[
        "台词信息密度过低",
        "演员表演生硬（破坏临场感）",
        "对白沦为“硬广播报”",
    ],
    sort_order=80,
)


_VISUAL_HOOK = HookPatternDefinition(
    id="visual_hook",
    name="视觉钩子",
    pattern_type="visual",
    description=(
        "用一个极具视觉冲击的画面开场——大色块、强对比光影、超慢动作、"
        "微距特写、漂亮的 ASMR 镜头。视觉钩子靠的不是文字也不是冲突，"
        "而是“美得让人手指停下来”。它特别适合产品本身具备视觉资产（食"
        "品、化妆品、香水、家居）的品类，但成本相对较高——需要专门的"
        "美术布光与镜头语言。如果不能稳定产出高品质画面，建议优先选其"
        "他钩子，避免“中等画质”反而拉低品牌感。"
    ),
    template_text=(
        "（开场：超慢动作特写，{{ product_name }} 的关键质感被光影放大）\n"
        "（无台词，只有 ASMR 音效与轻配乐 1.5-2s）\n"
        "（暗切到使用场景，画面节奏由慢转正常）\n"
        "字幕：有些东西，第一眼就值了。"
    ),
    psychology=(
        "审美愉悦反应（aesthetic chills）+ 视觉优先处理：人脑对高品质画面"
        "存在天然的注意力倾向，慢动作/微距能在 0.5s 内触发“想看清”的本能。"
    ),
    use_cases=[
        "产品具备高视觉资产（包装、纹理、光影）",
        "高客单价/高品牌感品类",
        "横屏/竖屏 9:16 都需要美感的双端投放",
    ],
    avoid_cases=[
        "画面品质无法稳定保证",
        "产品本身不具备视觉记忆点",
        "目标人群更看重价格信号而非美感",
    ],
    sort_order=90,
)


_POV_HOOK = HookPatternDefinition(
    id="pov_hook",
    name="第一人称钩子",
    pattern_type="pov",
    description=(
        "用第一人称视角（POV，Point Of View）开场——画面是主角看到的，"
        "观众像戴着主角的眼睛在体验整段内容。POV 钩子在 TikTok / 抖音"
        "信息流中越来越主流，因为它自带沉浸感、参与感、“我就是主角”的"
        "心流体验。它特别适合“展示型”内容（开箱、使用、试用、出行），"
        "但镜头节奏必须比第三人称视角更稳——POV 镜头一旦摇晃过度会快速"
        "诱发眩晕，损失 3 秒留存。"
    ),
    template_text=(
        "（POV 镜头：从主角视角向下，看到桌上的 {{ product_name }}）\n"
        "（手伸入画面拿起产品，缓慢转动展示）\n"
        "画外独白：今天我决定试一下这个——传说中能让 {{ context }} 不一样。\n"
        "（POV 切到使用场景）"
    ),
    psychology=(
        "第一人称视角主导自我归属感（self-ownership of action）：观众的镜"
        "像神经元被激活，“看着主角做”会被大脑解释为“我自己在做”，沉浸"
        "感与转化意愿同步上升。"
    ),
    use_cases=[
        "开箱、试用、使用流程展示",
        "出行、旅行、户外场景",
        "可穿戴/手持类设备产品",
    ],
    avoid_cases=[
        "镜头摇晃严重导致眩晕",
        "POV 与产品定位不符（高端品牌做廉价感 POV）",
        "POV 全程无对白且无字幕（信息密度太低）",
    ],
    sort_order=100,
)


#: 全量内置钩子定义，顺序即 ``sort_order`` 升序：
#: 1. question_hook（问句钩子）
#: 2. conflict_hook（冲突钩子）
#: 3. contrast_hook（对比钩子）
#: 4. numerical_hook（数字钩子）
#: 5. curiosity_hook（好奇钩子）
#: 6. shock_hook（震惊钩子）
#: 7. relatable_hook（共鸣钩子）
#: 8. dialogue_hook（对白钩子）
#: 9. visual_hook（视觉钩子）
#: 10. pov_hook（第一人称钩子）
BUILTIN_HOOK_PATTERN_DEFINITIONS: list[HookPatternDefinition] = [
    _QUESTION_HOOK,
    _CONFLICT_HOOK,
    _CONTRAST_HOOK,
    _NUMERICAL_HOOK,
    _CURIOSITY_HOOK,
    _SHOCK_HOOK,
    _RELATABLE_HOOK,
    _DIALOGUE_HOOK,
    _VISUAL_HOOK,
    _POV_HOOK,
]


# ---------------------------------------------------------------------------
# 幂等加载器
# ---------------------------------------------------------------------------


def _definition_to_orm_kwargs(definition: HookPatternDefinition) -> dict[str, Any]:
    """把 :class:`HookPatternDefinition` 转成 :class:`HookPattern` 字段字典。

    单独抽函数便于在 INSERT 与 UPDATE 路径上复用同一份字段映射，并与
    ``_diff_orm_against_payload`` 共享字段集做一致性判断。
    """
    return {
        "id": definition.id,
        "name": definition.name,
        "pattern_type": definition.pattern_type,
        "description": definition.description,
        "template_text": definition.template_text,
        "psychology": definition.psychology,
        "use_cases": list(definition.use_cases),
        "avoid_cases": list(definition.avoid_cases),
        "is_system": definition.is_system,
        "sort_order": definition.sort_order,
    }


def _diff_orm_against_payload(
    existing: HookPattern, payload: dict[str, Any]
) -> bool:
    """判断已有 ORM 行是否与目标字段完全一致。

    返回 ``True`` 表示存在差异、需要 UPDATE；返回 ``False`` 表示已经一致，
    可计入 ``unchanged``。JSON 列（``use_cases`` / ``avoid_cases``）按 Python
    等值比较即可。
    """
    for key, expected in payload.items():
        if key == "id":
            continue
        if getattr(existing, key) != expected:
            return True
    return False


async def bootstrap_builtin_hook_patterns(
    db: AsyncSession,
) -> dict[str, int]:
    """启动时调用，幂等地确保 10 条内置钩子模式存在于 ``hook_patterns`` 表中。

    幂等策略：
    - 以 ``HookPattern.id`` 作为业务键；
    - 不存在则 INSERT；
    - 存在但字段集与定义不一致则按定义 UPDATE（系统级模板每次启动都对齐
      到 canonical 版本，避免运营手动改库后被遗忘）；
    - 完全一致则跳过。

    Args:
        db: 异步数据库会话。函数内部会执行一次 ``commit()``，调用方不需要
            再外层包裹事务。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}``，N+M+K 等于
        :data:`BUILTIN_HOOK_PATTERN_DEFINITIONS` 的长度（当前为 10）。
    """
    counters: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}

    for definition in BUILTIN_HOOK_PATTERN_DEFINITIONS:
        payload = _definition_to_orm_kwargs(definition)
        existing = await db.get(HookPattern, definition.id)

        if existing is None:
            db.add(HookPattern(**payload))
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
    "HookPatternDefinition",
    "BUILTIN_HOOK_PATTERN_DEFINITIONS",
    "KNOWN_PATTERN_TYPES",
    "bootstrap_builtin_hook_patterns",
]
