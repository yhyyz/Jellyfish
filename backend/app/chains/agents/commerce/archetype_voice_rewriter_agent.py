"""ArchetypeVoiceRewriterAgent — 在保留镜头结构的前提下，按品牌人格改写脚本对白与旁白。

输入：
    - ``vars`` (``ArchetypeRewriteVars``)：原始 ``StoryScript`` 序列化 dict、
      目标 ``archetype`` 与自然语言描述、``tone_grid``、禁词与优先词汇。

输出：
    - ``StoryScript``：结构与输入完全一致（id / duration_sec / shot_type /
      camera_angle / camera_movement / 镜头数量 / brand_mention_count 不变），
      仅 ``dialog`` / ``narration`` / ``opening_hook`` / ``cta_text`` 等
      纯文本字段被改写为符合品牌人格的版本。

设计要点（与同 Wave 的 ``StoryScriptGeneratorAgent`` / ``CTAWriterAgent``
保持一致）：

1. ``method="json_schema"`` strict 的 structured output（D5 决策）；
2. 提示词正文直接来自 W3-T1 的 ``BUILTIN_PROMPT_DEFINITIONS``
   （``archetype_voice_rewriter_v1``），单一真相源、避免漂移；
3. ``format_output`` 重写：先尝试严格 JSON 解析，失败时使用 ``json-repair``
   兜底，容忍 LLM 常见的 unquoted key / trailing comma / Python 字面量等偏差；
4. 异步入口 ``a_rewrite_voice`` 在 LLM 输出后强制执行两道 post-extraction
   校验：``validate_structure_preserved`` 与 ``validate_words_to_avoid``，
   其中任一失败均抛 ``ValueError``，避免下游消费到结构被破坏或包含禁词的脚本；
5. ``archetype_voice_rewriter_v1`` 模板的输入变量为
   ``["archetype", "tone_grid", "original_script", "words_to_avoid",
   "preferred_vocab"]``；本 Agent 不修改该模板。``archetype_description``
   作为 ``ArchetypeRewriteVars`` 字段保留，由系统提示词层面引导 LLM 理解人格，
   即便模板未直接渲染该字段也能为后续模板演进留出接入点。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import (
    ArchetypeRewriteVars,
    StoryScript,
)
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "archetype_voice_rewriter_v1"

_STRUCTURE_PRESERVED_FIELDS: tuple[str, ...] = (
    "id",
    "duration_sec",
    "shot_type",
    "camera_angle",
    "camera_movement",
)


def _get_builtin_template_content(template_id: str) -> str:
    """从 W3-T1 注册表读取模板正文（单一真相源）。

    存在原因：
        避免在 Agent 文件里复制一份 prompt 文本，防止 W3-T1 与 W12-T3 间出现漂移。

    参数:
        template_id: ``BUILTIN_PROMPT_DEFINITIONS`` 中模板的 ``id``，
            例如 ``"archetype_voice_rewriter_v1"``。

    返回:
        Jinja2 模板源字符串。

    异常:
        ``KeyError``：当 ``template_id`` 在注册表中不存在时抛出，
        防止静默回退到错误模板。
    """
    for definition in BUILTIN_PROMPT_DEFINITIONS:
        if definition.id == template_id:
            return definition.template_content
    raise KeyError(f"builtin prompt not found: {template_id}")


_SYSTEM_PROMPT = (
    "你是品牌人格语气改写专家。\n"
    "任务：在保留 StoryScript 结构（shot 数量 / id / duration_sec / shot_type /\n"
    "camera_angle / camera_movement）的前提下，按指定 archetype + tone_grid\n"
    "改写每个 shot 的 dialog / narration 文本，并可同步改写 opening_hook / cta_text。\n"
    "\n"
    "铁律：\n"
    "1. 输出 shots 数量必须严格等于输入；\n"
    "2. 每个 shot 的 id 必须保留原值；\n"
    "3. duration_sec / shot_type / camera_angle / camera_movement 不可改；\n"
    "4. 仅改写文本字段：dialog / narration / opening_hook / cta_text；\n"
    "5. function 字段可微调描述，但不改语义；\n"
    "6. 严禁加入 words_to_avoid 中的任何词；\n"
    "7. 优先使用 preferred_vocab 中的词；\n"
    "8. brand_mention_count 与 is_brand_mention 镜位保持原值。\n"
    "\n"
    "只输出 StoryScript 完整 JSON，不要任何 Markdown 包裹。"
)


# 用户提示词模板：直接复用 W3-T1 注册的 jinja2 模板正文，单一真相源。
# 注：``archetype_voice_rewriter_v1`` 模板自身只渲染 5 个变量，但本 Agent 在
# input_variables 中额外声明 ``archetype_description``，目的是让上游 worker /
# API 可以把人格描述一并交给 ``aextract``，jinja2 引擎对未引用变量保持静默，
# 同时也为后续模板演进保留接入点（不必再改 Agent 调用方）。
ARCHETYPE_REWRITE_PROMPT = PromptTemplate(
    input_variables=[
        "original_script",
        "archetype",
        "archetype_description",
        "tone_grid",
        "words_to_avoid",
        "preferred_vocab",
    ],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


class ArchetypeVoiceRewriterAgent(AgentBase[StoryScript]):
    """品牌人格语气改写 Agent。

    职责：
        以 ``ArchetypeRewriteVars`` 为输入，驱动 LLM 在保留镜头结构的前提下
        按目标人格改写脚本文本，并对结构完整性与禁词命中做硬校验。

    关键设计：
        - structured output method 固定为 ``"json_schema"``（D5）；
        - prompt 模板直接引用 W3-T1 的 ``archetype_voice_rewriter_v1``，
          本 Agent 不修改该模板；
        - ``format_output`` 重写：严格 JSON → ``json-repair`` salvage → raise；
        - ``a_rewrite_voice`` 在 LLM 输出后强制执行两道 post-extraction 校验，
          确保下游不消费到结构破坏或含禁词的脚本。
    """

    def __init__(
        self,
        model: BaseChatModel,
        *,
        agent_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            model,
            structured_output_method="json_schema",
            agent_kwargs=agent_kwargs,
        )

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return ARCHETYPE_REWRITE_PROMPT

    @property
    def output_model(self) -> type[StoryScript]:
        return StoryScript

    def format_output(self, raw: str) -> StoryScript:
        """将 LLM 原始输出解析为 ``StoryScript``。

        策略：
            1. 先尝试 ``StoryScript.model_validate_json``（严格 JSON）；
            2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key、trailing
               comma、Python 字面量等）后再次校验。
            两次都失败时抛出 Pydantic ``ValidationError``，由上层调用方处理。

        参数:
            raw: LLM 原始字符串输出，期望为 JSON 文本。

        返回:
            校验通过的 ``StoryScript`` 实例。
        """
        try:
            return StoryScript.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            # 延迟导入：仅在严格解析失败时再加载 json-repair，降低启动开销。
            from json_repair import repair_json  # pylint: disable=import-outside-toplevel

            repaired = repair_json(
                raw,
                return_objects=True,
                skip_json_loads=False,
            )
            return StoryScript.model_validate(repaired)

    @staticmethod
    def validate_structure_preserved(
        original: StoryScript,
        rewritten: StoryScript,
    ) -> None:
        """改写后必须保留所有结构性字段。

        校验内容：
            1. ``shots`` 数量与原脚本一致；
            2. 每个对应位置的 shot 在 ``id`` / ``duration_sec`` / ``shot_type``
               / ``camera_angle`` / ``camera_movement`` 上保持原值；
            3. ``brand_mention_count`` 折算自 ``is_brand_mention=True``
               的镜数后与原脚本一致，确保品牌口播位置不被悄悄迁移。

        参数:
            original: 改写前的 ``StoryScript``。
            rewritten: LLM 改写后的 ``StoryScript``。

        异常:
            ``ValueError``：当任一结构性字段被改动时抛出，错误消息包含
            首个不一致字段的具体位置，便于排查。
        """
        if len(original.shots) != len(rewritten.shots):
            raise ValueError(
                "shot count changed: "
                f"original={len(original.shots)} "
                f"rewritten={len(rewritten.shots)}"
            )

        for orig_shot, new_shot in zip(original.shots, rewritten.shots):
            for field in _STRUCTURE_PRESERVED_FIELDS:
                if getattr(orig_shot, field) != getattr(new_shot, field):
                    raise ValueError(
                        f"shot {orig_shot.id} field {field} changed: "
                        f"{getattr(orig_shot, field)!r} -> "
                        f"{getattr(new_shot, field)!r}"
                    )

        # brand_mention_count 不变：以实际 is_brand_mention=True 镜数为准。
        orig_mentions = sum(1 for s in original.shots if s.is_brand_mention)
        new_mentions = sum(1 for s in rewritten.shots if s.is_brand_mention)
        if orig_mentions != new_mentions:
            raise ValueError(
                "brand_mention_count changed: "
                f"original={orig_mentions} rewritten={new_mentions}"
            )

    @staticmethod
    def validate_words_to_avoid(
        rewritten: StoryScript,
        words_to_avoid: list[str],
    ) -> None:
        """改写后不得含有禁用词。

        将所有可写文本字段（``opening_hook`` / ``cta_text`` /
        ``shots[*].dialog`` / ``shots[*].narration``）拼接为一段大字符串，
        逐项检查是否命中 ``words_to_avoid`` 中的任意词；命中则抛
        ``ValueError`` 并列出全部命中词，便于后置告警。

        参数:
            rewritten: LLM 改写后的 ``StoryScript``。
            words_to_avoid: 禁词列表，空列表时直接跳过校验。

        异常:
            ``ValueError``：当文本中出现任一禁词时抛出。
        """
        if not words_to_avoid:
            return

        text_parts: list[str] = [
            rewritten.opening_hook or "",
            rewritten.cta_text or "",
        ]
        text_parts.extend(s.dialog or "" for s in rewritten.shots)
        text_parts.extend(s.narration or "" for s in rewritten.shots)
        all_text = " ".join(part for part in text_parts if part)

        violations = [w for w in words_to_avoid if w and w in all_text]
        if violations:
            raise ValueError(f"words_to_avoid violated: {violations}")

    async def a_rewrite_voice(  # pylint: disable=redefined-builtin
        self,
        *,
        vars: ArchetypeRewriteVars,
    ) -> StoryScript:
        """异步入口：基于 ``ArchetypeRewriteVars`` 输出经品牌人格改写后的脚本。

        流程：
            1. 把 ``original_script`` 反序列化为 ``StoryScript``，作为
               post-extraction 校验的基准（保证下游能拿到强类型对照）；
            2. 通过 ``model_dump()`` 获取所有字段作为提示词渲染参数，
               依赖 ``ConfigDict(extra="forbid")`` 保证不会注入意外字段；
            3. ``aextract`` 优先走 structured output，失败时回退到
               ``arun + format_output``（json-repair salvage）；
            4. 对返回的 ``StoryScript`` 依次执行：
               - ``validate_structure_preserved``
               - ``validate_words_to_avoid``
               任一失败将抛 ``ValueError``，避免下游消费到不合格脚本。

        参数:
            vars: ``ArchetypeRewriteVars`` 实例，封装改写所需上下文。

        返回:
            校验通过的 ``StoryScript`` 实例。

        异常:
            ``ValueError``：当 LLM 输出不符合结构保留 / 禁词约束时抛出。
        """
        original = StoryScript.model_validate(vars.original_script)
        kwargs = vars.model_dump()
        rewritten = await self.aextract(**kwargs)
        # 双重保险：在 schema 校验之外再加一层业务硬约束。
        self.validate_structure_preserved(original, rewritten)
        self.validate_words_to_avoid(rewritten, vars.words_to_avoid)
        return rewritten
