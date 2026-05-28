"""Archetype + Brand-Tone 硬约束 validator —— P4 W25-T2，Wave C 2/3。

为什么存在：
    LLM 生成出的 ``StoryVariant.script_breakdown`` 受品牌侧两条软硬约束
    挟制：

    1. **品牌话术规范（BrandStyleGuide）**：每个 Product 配 1:1 的禁用
       句式 / 必备收尾 / 品牌人格 tagline，是"老板拍板的红线"，不允
       许由 LLM 自由发挥；
    2. **品牌人格原型（BrandArchetype）**：每个 variant 选定一种
       archetype（sage / jester / rebel ...），理论上对白调性需要靠近
       该原型的关键词词袋，避免 generator 跑偏成另一种人格。

    本 validator 把上述两层约束压成 **纯函数**，输出一个人类可读的
    issues 列表，由后续 wave 串入 ``retry_with_validator`` helper（见
    :mod:`app.chains.agents._retry`，T25-1 已落地），让
    ArchetypeVoiceRewriterAgent / StoryScriptGenerator 的失败结果能带着
    具体违规理由触发一次带 guidance 的重试，而不是黑盒重跑。

为什么是纯函数：
    * 不依赖 ORM session、不依赖 settings、不发起 LLM 调用——仅
      接受 dict 形参；
    * 可独立单测，便于 TDD（≥5 用例覆盖几条主路径）；
    * 与 T25-1 的 ``build_competitor_validator`` 接口形态一致：让上层
      retry helper 用同一种 ``Callable[[str], list[str]]`` /
      ``Callable[[dict, ...], list[str]]`` 模式串接，不需要为本 validator
      单独走一条特殊路径；
    * 不接入 orchestrator —— 本任务（W25-T2）刻意只落 validator，
      避免触碰 P2 W12 ArchetypeVoiceRewriterAgent 内部，留给后续 wave
      做集成。

校验维度（按命中即加 issue）：
    1. **banned_patterns**：``brand_style_guide.banned_patterns`` 中任一
       字符串若在任一 dialogue 文本里出现，即记一条 issue（含命中模式）。
    2. **required_endings**：``brand_style_guide.required_endings`` 至
       少需有 1 个出现在 **最后一镜** 的 dialogue 中；否则记一条 issue。
       仅对最后一镜检查，避免在中间镜出现就放过的"假合规"。
    3. **brand_persona_tagline 关键词**：若 tagline 非空，从 tagline
       中切出关键词；若所有 dialogue 加起来都没出现任一关键词，记一
       条软提醒 issue。tagline 是 LLM 注入用的语义短描述，命中率不强求。
    4. **archetype 关键词命中率**：根据 ``product_archetype`` 取
       预定义 keyword bag，检查"出现过的 keyword 数 / keyword bag 总数"是
       否 ≥ 阈值（默认 0.05，足够宽松——10 词 bag 仅需 1 命中即通过）。
       这条主要兜底"调性彻底跑偏"的 generator 输出，而非细粒度审稿。

入参 / 出参：
    * ``variant_payload``：通常是 ``StoryVariant.script_breakdown``
      整体或一份内容相同的 dict；本函数同时兼容两种 dialogue 来源：

      - 显式 ``dialogues``: list[str | dict]（task spec 直觉形态）；
      - ``shots[*].dialog`` / ``shots[*].narration``（实际持久化形态，
        :class:`app.core.contracts.story.StoryScript` 的 dump 形）。

    * ``brand_style_guide``：可空 dict（来自
      :class:`BrandStyleGuide` ORM 行的字段映射）。``None`` 视为"商品
      没挂规范库"，本 validator 直接放行（不返回任何 issue），让上层
      区分"没有规范库"与"违反规范"。
    * ``product_archetype``：可空字符串（``BrandArchetype.id``，与
      :class:`app.models.types.BrandArchetype` 枚举值一致）；不在 keyword
      bag 表内的 archetype 视为未注册，本维度直接放行。

边界 / 防御性：
    * 任意子结构缺失（``script_breakdown`` 缺 ``shots`` / ``dialogues``、
      shot 缺 ``dialog`` / ``narration``）均被视为"无 dialogue 可校验"，
      不会抛异常，但仍会让 banned/required/persona/archetype 各维度做
      自己的早退判断；
    * dialogues 中的非字符串元素（dict / None / 数字）会被尽力提取或
      跳过，不影响整体扫描；
    * 阈值默认 0.05，调用方可显式传 ``archetype_threshold`` 覆盖。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# ---------------------------------------------------------------------------
# 常量 / 词袋
# ---------------------------------------------------------------------------

#: archetype keyword 命中率默认阈值。0.05 = 词袋中至少 5% 的 keyword
#: 至少出现过一次。10 词的小词袋仅需 1 命中即通过，故"宽松兜底"。
DEFAULT_ARCHETYPE_THRESHOLD = 0.05

#: 12 类 BrandArchetype 的最小关键词词袋（中英混合）。
#:
#: 设计取舍：
#:     * 故意只用 8-12 个高识别度词，避免 false positive 拖累 generator；
#:     * 中英混合是因为脚本可能掺英文 punchline / 品牌词；
#:     * 与 :class:`BrandArchetype.voice_traits` 不直接同源——voice_traits
#:       是给 LLM 看的"形容词卡片"，本词袋是给纯文本扫描看的"硬关键词"，
#:       两者用途不同，不建议直接复用。
ARCHETYPE_KEYWORD_BAGS: dict[str, tuple[str, ...]] = {
    "sage": ("智慧", "深思", "洞察", "哲理", "睿智", "审视", "学识", "wisdom", "insight"),
    "jester": ("有趣", "好玩", "搞笑", "幽默", "嘿嘿", "哈哈", "fun", "joke"),
    "rebel": ("打破", "颠覆", "反叛", "拒绝", "不一样", "rebel", "break"),
    "provocateur": ("挑战", "挑衅", "敢不敢", "刺激", "敢", "provoke", "dare"),
    "maverick": ("独行", "另辟", "独立", "敢闯", "我行我素", "maverick"),
    "friend": ("陪伴", "朋友", "一起", "我们", "暖", "贴心", "friend", "together"),
    "expert": ("专业", "权威", "认证", "专家", "实测", "数据", "expert", "proven"),
    "cheerleader": ("加油", "你可以", "相信", "燃", "冲", "go", "yes"),
    "storyteller": ("故事", "曾经", "那一年", "她说", "回忆", "story", "once"),
    "analyst": ("数据", "分析", "对比", "结果", "结论", "因此", "analysis"),
    "coach": ("一步", "学会", "练习", "习惯", "训练", "进步", "coach", "step"),
    "minimalist": ("极简", "简单", "少即是多", "纯粹", "干净", "simple", "less"),
}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    """把 dialogue 元素尽力还原成可扫描字符串。

    支持两种形态：
        * 直接是字符串；
        * dict 形（含 ``text`` / ``content`` / ``dialog`` / ``narration``
          其一）——挑第一个非空字段。

    其它（None / 数字 / 列表）一律视为空串，让扫描循环安全跳过。
    """

    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "dialog", "narration", "line"):
            text = value.get(key)
            if isinstance(text, str) and text:
                return text
    return ""


def _extract_dialogues(script_breakdown: Any) -> list[str]:
    """从 ``script_breakdown`` 抽取按出场顺序排列的 dialogue 字符串列表。

    支持两种实际/直觉形态：
        1. ``script_breakdown.dialogues``：list[str | dict]，task spec
           的直觉描述，主要用于上层手动构造 payload；
        2. ``script_breakdown.shots[*].dialog`` / ``narration``：真实持
           久化的 StoryScript dump 形（见
           :class:`app.core.contracts.story.Shot`）。同一 shot 的 dialog
           与 narration 都会被收进来，按 dialog 在前 / narration 在后
           的顺序追加，保持镜次序号语义。

    若两种 key 都没命中，返回空列表（让上层各维度自行决定要不要早退）。
    """

    if not isinstance(script_breakdown, dict):
        return []

    dialogues: list[str] = []

    raw_dialogues = script_breakdown.get("dialogues")
    if isinstance(raw_dialogues, list):
        for item in raw_dialogues:
            text = _coerce_str(item)
            if text:
                dialogues.append(text)

    shots = script_breakdown.get("shots")
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            for key in ("dialog", "narration"):
                text = shot.get(key)
                if isinstance(text, str) and text:
                    dialogues.append(text)

    return dialogues


def _extract_last_shot_dialogue(script_breakdown: Any) -> str:
    """提取"最后一镜"的合并 dialogue 文本，用于 required_endings 检查。

    优先级：
        1. ``shots`` 列表非空 → 取末元素的 dialog + narration 拼接；
        2. ``dialogues`` 列表非空 → 取末元素的 ``_coerce_str``；
        3. 都没有 → 返回空串（caller 自行决定是否记 issue）。

    把 dialog 与 narration 一起纳入末尾镜的可命中文本，是因为
    "必备收尾短语"既可能在角色对白里也可能在旁白里出现——CTA 语
    经常是旁白形态，强行只看 dialog 会出现"明明 narration 里有 CTA
    却被标违规"的反直觉用例。
    """

    if not isinstance(script_breakdown, dict):
        return ""

    shots = script_breakdown.get("shots")
    if isinstance(shots, list) and shots:
        last_shot = shots[-1]
        if isinstance(last_shot, dict):
            parts: list[str] = []
            for key in ("dialog", "narration"):
                text = last_shot.get(key)
                if isinstance(text, str) and text:
                    parts.append(text)
            if parts:
                return "\n".join(parts)

    raw_dialogues = script_breakdown.get("dialogues")
    if isinstance(raw_dialogues, list) and raw_dialogues:
        return _coerce_str(raw_dialogues[-1])

    return ""


# 关键词抽取：CJK 用滑动 2-gram，ASCII 走 ≥3 字母 token，避开 the/and 等噪声。
_TAGLINE_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_TAGLINE_ASCII_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


def _extract_tagline_keywords(tagline: str) -> list[str]:
    """从 brand_persona_tagline 抽可在对白里寻找的关键词。

    策略：
        * 不引入分词器（jieba 等），保持 validator 零依赖；
        * **CJK 段走滑动 2-gram**：例如 "用专业团队为你打磨细节"
          会被切成 [用专, 专业, 业团, 团队, ...]。这样只要对白出现
          其中任意 2 字组合（"专业" / "团队"），就算 tagline 关键词
          被提及。直接用整段 CJK 长串做包含判断会过严，因为对白
          很难原样复读 tagline；
        * **ASCII token ≥ 3 字母**：避开 the / and 等噪声词；
        * 重复 token 去重，保留首次出现顺序，保留原始大小写。
    """

    if not tagline:
        return []

    keywords: list[str] = []
    seen: set[str] = set()

    def _push(token: str) -> None:
        normalized = token.lower()
        if normalized in seen:
            return
        seen.add(normalized)
        keywords.append(token)

    for cjk_run in _TAGLINE_CJK_RUN_RE.findall(tagline):
        if len(cjk_run) == 1:
            # 单字 CJK 命中价值低（如 "你" / "的"），跳过避免假阳性。
            continue
        for i in range(len(cjk_run) - 1):
            _push(cjk_run[i : i + 2])

    for ascii_token in _TAGLINE_ASCII_TOKEN_RE.findall(tagline):
        _push(ascii_token)

    return keywords


def _archetype_hit_rate(
    dialogues_text: str,
    keyword_bag: Iterable[str],
) -> tuple[float, list[str]]:
    """计算 archetype 词袋的命中率（已出现过 / 总数），并返回未命中项。

    命中标准是"keyword 至少出现一次"（不计次数），与 task spec 里的
    "词频命中率"语义一致：评估的是 *coverage*，不是 *frequency*——
    如果一个关键词重复 100 次，只能算一次"命中过"，避免 generator 用
    单一关键词刷分。
    """

    bag = [k for k in keyword_bag if k]
    if not bag:
        return 1.0, []

    if not dialogues_text:
        return 0.0, list(bag)

    haystack = dialogues_text.lower()
    hit_count = 0
    missed: list[str] = []
    for keyword in bag:
        if keyword.lower() in haystack:
            hit_count += 1
        else:
            missed.append(keyword)
    return hit_count / len(bag), missed


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def validate_archetype_tone(
    variant_payload: dict[str, Any],
    brand_style_guide: dict[str, Any] | None,
    product_archetype: str | None,
    *,
    archetype_threshold: float = DEFAULT_ARCHETYPE_THRESHOLD,
) -> list[str]:
    """检查 variant_payload 是否符合品牌话术规范 + archetype 调性。

    Args:
        variant_payload: 整个 variant 的 dict（一般是 ``StoryVariant``
            的 ``script_breakdown`` 字段；也接受顶层带 ``script_breakdown``
            的 wrapper dict——优先识别 wrapper）。
        brand_style_guide: ``BrandStyleGuide`` 字段映射，缺省 ``None``
            视为"商品未挂规范"，直接放行。期望键：``forced_phrases`` /
            ``banned_patterns`` / ``required_endings`` /
            ``brand_persona_tagline``。
        product_archetype: ``BrandArchetype.id``；若为 ``None`` 或不在
            :data:`ARCHETYPE_KEYWORD_BAGS` 注册表，archetype 维度直接放行。
        archetype_threshold: archetype 关键词命中率下限，默认
            :data:`DEFAULT_ARCHETYPE_THRESHOLD`（0.05，宽松兜底）。

    Returns:
        ``list[str]``：每条 issue 是一条人类可读的违规描述。空列表表示
        通过。issue 文案设计成"包含命中关键词 / 字段名"，便于后续 wave
        把它直接拼进 ``retry_with_validator`` 的 guidance 反馈给 agent。
    """

    issues: list[str] = []

    # 兼容两种入参语义：直接传 script_breakdown，或传含 script_breakdown
    # 的 wrapper dict。优先取 wrapper 形态，让 caller 不必先剥一层壳。
    if isinstance(variant_payload, dict) and "script_breakdown" in variant_payload:
        script_breakdown = variant_payload.get("script_breakdown") or {}
    else:
        script_breakdown = variant_payload or {}

    dialogues = _extract_dialogues(script_breakdown)
    last_shot_dialogue = _extract_last_shot_dialogue(script_breakdown)

    if not brand_style_guide:
        # 没挂规范库时只校验 archetype 调性；规范类硬约束跳过。
        return _archetype_only_check(
            dialogues,
            product_archetype,
            archetype_threshold,
        )

    # 1. banned_patterns 硬扫描
    banned_patterns = brand_style_guide.get("banned_patterns") or []
    if isinstance(banned_patterns, list):
        joined_dialogues = "\n".join(dialogues)
        hit_patterns: list[str] = []
        for pattern in banned_patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                continue
            if pattern in joined_dialogues:
                hit_patterns.append(pattern)
        if hit_patterns:
            joined = "、".join(hit_patterns)
            issues.append(
                f"对白命中品牌禁用句式：{joined}，请改用合规表达。"
            )

    # 2. required_endings 末镜命中
    required_endings = brand_style_guide.get("required_endings") or []
    if isinstance(required_endings, list):
        cleaned_endings = [e for e in required_endings if isinstance(e, str) and e.strip()]
        if cleaned_endings:
            if not last_shot_dialogue:
                issues.append(
                    f"最后一镜没有 dialogue/narration，无法承载必备结尾："
                    f"{cleaned_endings}"
                )
            elif not any(end in last_shot_dialogue for end in cleaned_endings):
                joined = "、".join(cleaned_endings)
                issues.append(
                    f"最后一镜对白未包含任一必备结尾：{joined}，请在收口处补齐。"
                )

    # 3. brand_persona_tagline 关键词覆盖（软提醒）
    tagline = brand_style_guide.get("brand_persona_tagline") or ""
    if isinstance(tagline, str):
        tagline_keywords = _extract_tagline_keywords(tagline)
        if tagline_keywords:
            haystack = "\n".join(dialogues).lower()
            if not any(k.lower() in haystack for k in tagline_keywords):
                joined = "、".join(tagline_keywords)
                issues.append(
                    f"对白未提及品牌人格 tagline 关键词（{joined}），"
                    f"建议在适当镜头自然嵌入以强化品牌识别度。"
                )

    # 4. archetype 关键词命中率兜底
    issues.extend(_archetype_only_check(dialogues, product_archetype, archetype_threshold))

    return issues


def _archetype_only_check(
    dialogues: list[str],
    product_archetype: str | None,
    archetype_threshold: float,
) -> list[str]:
    """单独跑 archetype 词袋命中率检查；其他维度由 caller 处理。

    被 :func:`validate_archetype_tone` 在两条路径上复用：

    * 没有 brand_style_guide 时（只校验调性，不校验规范）；
    * 有 brand_style_guide 时（在末尾追加 archetype 维度结果）。
    """

    if not product_archetype:
        return []

    keyword_bag = ARCHETYPE_KEYWORD_BAGS.get(product_archetype.lower())
    if not keyword_bag:
        # 未注册的 archetype 不强加约束——避免误伤新增/未知原型。
        return []

    dialogues_text = "\n".join(dialogues)
    rate, missed = _archetype_hit_rate(dialogues_text, keyword_bag)
    if rate >= archetype_threshold:
        return []

    sample = "、".join(missed[:5])
    return [
        f"archetype '{product_archetype}' 调性关键词命中率 {rate:.2%} "
        f"低于阈值 {archetype_threshold:.0%}，建议在对白中体现："
        f"{sample}"
    ]


__all__ = [
    "ARCHETYPE_KEYWORD_BAGS",
    "DEFAULT_ARCHETYPE_THRESHOLD",
    "validate_archetype_tone",
]
