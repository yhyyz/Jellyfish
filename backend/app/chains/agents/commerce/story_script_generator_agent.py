"""StoryScriptGeneratorAgent — 给定剧情公式 + 商品 + 受众 + 品牌人格，输出完整 StoryScript JSON。

输入：``StoryGenerationVars``（formula / product / audience / archetype /
tone_grid / target_duration_sec / platform）。
输出：``StoryScript``（含 ``shots: list[Shot]`` 嵌套数组）。

关键约束（运行时由 ``a_generate_script`` 内部静态校验器强制）：

1. ``total_duration_sec`` 与 ``target_duration_sec`` 偏差 ≤10%；
2. 商品出现 3 次（subtle / functional / hero 三档）——schema 不强制次数，
   提示词层面引导，必要时由独立 validator 增强（本 Agent 已在 prompt 中说明）；
3. ``brand_mention_count ≤ 2 per 60s``（rate-cap 安全网）；
4. 镜头数 3 ≤ N ≤ 30（schema 已限制，agent 端不重复约束）。

Provider 策略（参见 ``.omo/notepads/jellyfish-story-commerce/decisions.md`` D5
与 ``research.md`` §4）：

- ``method="json_schema", strict=True``，Pydantic v2 ``ConfigDict(extra="forbid")``；
- ``format_output`` 三段式：严格 ``model_validate_json`` → ``json-repair`` salvage → raise；
- ``max_tokens`` 默认 6000；超长脚本（>120s）建议提升到 8192，由调用方通过
  ``model.bind(max_tokens=...)`` 决定。

参考：
    - W3-T1 ``BUILTIN_PROMPT_DEFINITIONS["story_formula_generator_v1"]``；
    - ``app/core/contracts/story.py`` 中 ``StoryScript`` / ``Shot`` /
      ``StoryGenerationVars`` 契约。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import StoryGenerationVars, StoryScript
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "story_formula_generator_v1"


def _get_builtin_template_content(template_id: str) -> str:
    """从 W3-T1 注册表读取模板正文（单一真相源）。

    存在原因：
        提示词正文统一由 ``BUILTIN_PROMPT_DEFINITIONS`` 维护，避免 Agent
        文件复制一份导致与 W3-T1 漂移；同时强制每个模板 ``id`` 对应唯一
        模板，未命中即报错而非静默退化。

    参数:
        template_id: ``BUILTIN_PROMPT_DEFINITIONS`` 中模板的 ``id``，
            例如 ``"story_formula_generator_v1"``。

    返回:
        Jinja2 模板正文字符串。

    异常:
        ``KeyError``：当 ``template_id`` 在注册表中不存在时抛出。
    """
    for definition in BUILTIN_PROMPT_DEFINITIONS:
        if definition.id == template_id:
            return definition.template_content
    raise KeyError(f"builtin prompt not found: {template_id}")


_SYSTEM_PROMPT = """你是中文剧情带货脚本生成专家。
你输出严格符合 StoryScript schema 的 JSON。每个 Shot 字段（duration_sec /
function / shot_type / camera_angle / camera_movement / dialog / narration /
product_focus_level / is_punchline / is_brand_mention / notes）都要填充合理值。

铁律：
1. shots 总时长（duration_sec 累加）必须 ≈ target_duration_sec（±10% 内）。
2. 商品出现节奏：第 1/2 镜 subtle 自然带出 → 中段 functional 解决痛点 →
   末段 hero 高光收尾。
3. brand_mention_count（is_brand_mention=true 的镜数）≤ 2 per 60s。
4. opening_hook 文本必须 < 3 秒可读（约 18 字）。
5. cta_text 转化语句必须包含 product_name 引用。

只输出 JSON，不要任何 Markdown 包裹。"""


# 用户提示词模板：直接复用 W3-T1 注册的 jinja2 模板正文，单一真相源。
STORY_GENERATOR_PROMPT = PromptTemplate(
    input_variables=[
        "formula",
        "product",
        "audience",
        "archetype",
        "tone_grid",
        "target_duration_sec",
        "platform",
    ],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


class StoryScriptGeneratorAgent(AgentBase[StoryScript]):
    """剧情脚本生成 Agent —— 整合公式 + 商品 + 受众 + 品牌人格输出完整 StoryScript。

    职责：
        以 ``StoryGenerationVars`` 为输入，驱动 LLM 产出符合 ``StoryScript``
        schema 的脚本，并对时长漂移与品牌口播频率做硬校验。

    关键设计：
        - structured output method 固定为 ``"json_schema"``（D5）；
        - prompt 模板直接引用 W3-T1 ``BUILTIN_PROMPT_DEFINITIONS``；
        - ``format_output`` 重写：严格 JSON → ``json-repair`` salvage → raise；
        - ``a_generate_script`` 在 LLM 输出之后再做一轮静态校验，保证业务
          约束一致性，避免下游消费到不合格的脚本。
    """

    # >120s 脚本建议使用更高 token 上限；本类只暴露常量，绑定由调用方做。
    DEFAULT_MAX_TOKENS_LONG: int = 8192
    DEFAULT_MAX_TOKENS_SHORT: int = 6000

    def __init__(
        self,
        model: BaseChatModel,
        *,
        agent_kwargs: dict[str, Any] | None = None,
    ) -> None:
        # D5：商品 / 脚本 / 合规三个新 commerce agent 一律使用 json_schema strict。
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
        return STORY_GENERATOR_PROMPT

    @property
    def output_model(self) -> type[StoryScript]:
        return StoryScript

    def format_output(self, raw: str) -> StoryScript:
        """将 LLM 原始输出解析为 ``StoryScript``。

        三段式策略：

        1. 先尝试 ``StoryScript.model_validate_json``（严格 JSON）；
        2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key /
           trailing comma / 缺右括号 / Python 字面量）后再次校验；
        3. 两次都失败则向上抛出原始 Pydantic ``ValidationError`` /
           ``ValueError``，由上层调用方处理。

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
    def validate_duration_drift(
        script: StoryScript,
        target_duration_sec: int,
        tolerance_pct: float = 0.10,
    ) -> None:
        """对最终输出的脚本时长漂移做硬校验。

        计算所有镜头 ``duration_sec`` 的累加值与 ``target_duration_sec`` 的
        相对偏差，超过 ``tolerance_pct`` 即抛出 ``ValueError``，避免下游
        消费到时长严重失配的脚本。

        参数:
            script: 待校验的 ``StoryScript`` 实例。
            target_duration_sec: 期望脚本总时长（秒），来自
                ``StoryGenerationVars.target_duration_sec``。
            tolerance_pct: 允许的相对漂移比例，默认 10%。

        异常:
            ``ValueError``：当实际时长漂移超过容差时抛出。
        """
        actual = sum(s.duration_sec for s in script.shots)
        drift = abs(actual - target_duration_sec) / target_duration_sec
        if drift > tolerance_pct:
            raise ValueError(
                f"duration drift {drift:.1%} exceeds tolerance "
                f"{tolerance_pct:.0%}: target={target_duration_sec}s "
                f"actual={actual:.1f}s"
            )

    @staticmethod
    def validate_brand_mention_cap(
        script: StoryScript,
        *,
        target_duration_sec: int,
        cap_per_60s: int = 2,
    ) -> None:
        """品牌口播频率上限校验。

        将 ``cap_per_60s``（默认 2）按 ``target_duration_sec`` 折算为绝对
        上限，若实际 ``is_brand_mention=True`` 镜头数超过该上限，抛出
        ``ValueError``，作为商家硬广感的最后防线。

        参数:
            script: 待校验的 ``StoryScript`` 实例。
            target_duration_sec: 期望脚本总时长（秒），决定折算后的上限。
            cap_per_60s: 每 60 秒允许的品牌口播次数上限，默认 2。

        异常:
            ``ValueError``：当实际口播镜头数超过折算上限时抛出。
        """
        cap = max(1, int(round(cap_per_60s * target_duration_sec / 60)))
        mentions = sum(1 for s in script.shots if s.is_brand_mention)
        if mentions > cap:
            raise ValueError(
                f"brand_mention_count {mentions} exceeds cap {cap} "
                f"for {target_duration_sec}s"
            )

    async def a_generate_script(
        self,
        *,
        vars: StoryGenerationVars,  # pylint: disable=redefined-builtin
    ) -> StoryScript:
        """异步入口：根据 ``StoryGenerationVars`` 生成完整 ``StoryScript``。

        流程：
            1. ``StoryGenerationVars`` 因 ``ConfigDict(extra="forbid")`` 仅
               导出声明字段，``model_dump()`` 直接喂给模板渲染；
            2. ``aextract`` 优先走 structured output，失败时回退到
               ``arun + format_output``（json-repair salvage）；
            3. 对返回的 ``StoryScript`` 做时长漂移与品牌口播上限校验；
               任一失败将抛出 ``ValueError``，避免下游消费到不合格脚本。

        参数:
            vars: ``StoryGenerationVars`` 实例，封装 prompt 渲染所需上下文。

        返回:
            校验通过的 ``StoryScript`` 实例。

        异常:
            ``ValueError``：当 LLM 输出不符合时长 / 口播硬约束时抛出。
        """
        # Pydantic v2: ConfigDict(extra="forbid") 确保 model_dump() 仅返回声明字段。
        kwargs = vars.model_dump()
        script = await self.aextract(**kwargs)
        # 双重保险：在 schema 校验之外再加一层业务硬约束。
        self.validate_duration_drift(script, vars.target_duration_sec)
        self.validate_brand_mention_cap(
            script,
            target_duration_sec=vars.target_duration_sec,
        )
        return script
