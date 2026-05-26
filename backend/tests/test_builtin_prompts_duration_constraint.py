"""``_STORY_FORMULA_GENERATOR`` 时长硬约束 + ``_DURATION_REWRITER`` 模板测试
（P3 W17 T17-8）。

为何存在
--------

T17-8 把 Decision F 决策树的字数约束往上游推到 LLM prompt 端：
``story_formula_generator`` 在生成脚本时就要避免出 dialog/narration
字数严重超过 ``duration_sec * 3 (旁白) / 4 (对白)`` 的镜头，
否则下游 ``ChapterAvPlanner`` 必然反复触发 LLM 回灌（R-P3-3）。

本测试钉住三件事：

1. ``_STORY_FORMULA_GENERATOR`` 模板正文包含明确的“字数硬约束”表述；
2. Shot schema 区段把 ``dialog`` / ``narration`` 字段的字数上限写进了
   面向 LLM 的强约束语；
3. 新模板常量 ``_DURATION_REWRITER`` 已在 ``builtin_prompts`` 模块里
   注册并暴露，供 ``DurationRewriterAgent`` 直接消费。
"""

# pylint: disable=protected-access

from __future__ import annotations

import re

import pytest

from app.services.studio import builtin_prompts
from app.services.studio.builtin_prompts import (
    BUILTIN_PROMPT_DEFINITIONS,
    render_template,
)


# ---------------------------------------------------------------------------
# 1. _STORY_FORMULA_GENERATOR 包含 duration 字数硬约束
# ---------------------------------------------------------------------------


def test_story_formula_generator_template_contains_duration_char_constraint() -> None:
    """模板必须出现 ``≤ N × duration_sec`` 这种字数硬约束表达。"""

    template = builtin_prompts._STORY_FORMULA_GENERATOR
    # 任意 3 或 4 倍 duration_sec 的硬约束都接受，不锁死表述顺序。
    pattern = re.compile(r"(3|4)\s*[×x*]\s*duration_sec")
    assert pattern.search(template), (
        "story_formula_generator 模板必须包含 dialog/narration 字数硬约束 "
        "（例如 '≤ 3 × duration_sec' 形式），便于 LLM 自约束输出长度。"
    )


def test_story_formula_generator_mentions_per_shot_duration_limit() -> None:
    """模板必须明确告诉 LLM「本镜头 N 秒，台词 ≤ ...」。"""

    template = builtin_prompts._STORY_FORMULA_GENERATOR
    # 文案必须出现“硬约束”相关的字数上限提示。
    assert (
        "字符数" in template or "字数" in template
    ), "story_formula_generator 必须在硬约束区段提及字数上限"


def test_story_formula_generator_shot_schema_dialog_field_has_char_cap() -> None:
    """Shot schema 区段的 ``dialog`` / ``narration`` 字段描述需带字数上限提醒。"""

    template = builtin_prompts._STORY_FORMULA_GENERATOR
    # Shot schema 区段（``"dialog":`` 与 ``"narration":`` 行附近）应提及字数限制。
    # 这里用宽松断言：只要在字段描述附近的窗口里出现字数 / 上限关键词即可。
    dialog_idx = template.find('"dialog"')
    narration_idx = template.find('"narration"')
    assert dialog_idx > 0
    assert narration_idx > 0
    # 字段描述行后续 200 字符内应能搜到字数 / duration_sec 上限相关字样。
    window = template[dialog_idx : narration_idx + 200]
    assert (
        "duration_sec" in window or "字" in window
    ), "Shot schema 的 dialog/narration 字段描述需要带字数上限提示"


# ---------------------------------------------------------------------------
# 2. 模板渲染仍然保持兼容
# ---------------------------------------------------------------------------


def test_story_formula_generator_template_renders_with_existing_fixture() -> None:
    """模板更新后仍可被 canonical fixture 渲染（变量声明未漂移）。"""

    definition = next(
        (d for d in BUILTIN_PROMPT_DEFINITIONS if d.id == "story_formula_generator_v1"),
        None,
    )
    assert definition is not None
    sample = {
        "formula": {"id": "x", "beats": []},
        "product": {"name": "p"},
        "audience": {"age_range": "25-34"},
        "archetype": "sage",
        "tone_grid": {"formal": 5},
        "target_duration_sec": 60,
        "platform": "douyin",
    }
    rendered = render_template(definition.template_content, sample, strict=True)
    # 渲染后应仍然包含约束区块，且包含字数硬约束关键词。
    assert "硬性约束" in rendered
    assert "duration_sec" in rendered


# ---------------------------------------------------------------------------
# 3. _DURATION_REWRITER 模板已注册
# ---------------------------------------------------------------------------


def test_duration_rewriter_template_constant_is_exported() -> None:
    """``_DURATION_REWRITER`` 必须作为模块属性存在，供 Agent 直接 import。"""

    assert hasattr(builtin_prompts, "_DURATION_REWRITER")
    template = builtin_prompts._DURATION_REWRITER
    assert isinstance(template, str)
    assert template.strip()
    # 模板必须暴露 target_chars 与 line_mode 这两个关键变量占位。
    assert "{{ target_chars }}" in template
    assert "{{ line_mode }}" in template
    assert "{{ original_text }}" in template


def test_duration_rewriter_template_renders_with_minimal_vars() -> None:
    """模板必须能在 strict 模式下用最小上下文渲染通过。"""

    rendered = render_template(
        builtin_prompts._DURATION_REWRITER,
        {
            "original_text": "原始台词",
            "target_chars": 10,
            "line_mode": "DIALOGUE",
        },
        strict=True,
    )
    assert "原始台词" in rendered
    assert "10" in rendered
    assert "DIALOGUE" in rendered


def test_duration_rewriter_template_explains_target_chars_constraint() -> None:
    """模板必须告知 LLM 「输出 ≤ target_chars 字符」，否则 Agent 自校验会反复失败。"""

    template = builtin_prompts._DURATION_REWRITER
    # 接受多种自然表述，但必须出现“≤ target_chars”相关语义关键词。
    assert "target_chars" in template
    assert ("≤" in template) or ("不超过" in template) or ("<=" in template)


# ---------------------------------------------------------------------------
# 4. 模板字段约定：仅返回 ``rewritten_text`` + ``char_count``
# ---------------------------------------------------------------------------


def test_duration_rewriter_template_describes_output_schema() -> None:
    """模板必须指明输出 JSON schema：``rewritten_text`` + ``char_count``。"""

    template = builtin_prompts._DURATION_REWRITER
    assert "rewritten_text" in template
    assert "char_count" in template


# ---------------------------------------------------------------------------
# 5. 注册表数量保持 27（避免 PromptCategory 漂移影响其它测试）
# ---------------------------------------------------------------------------


def test_builtin_definitions_count_unchanged_at_27() -> None:
    """T17-8 不允许引入新的 PromptCategory：BUILTIN_PROMPT_DEFINITIONS 仍为 27 项。"""

    assert len(BUILTIN_PROMPT_DEFINITIONS) == 27


# ---------------------------------------------------------------------------
# 6. AGENTS.md 注释要求：模板包含 zh 文档说明
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needle",
    [
        "duration_sec",
        "字数",
    ],
)
def test_story_formula_generator_template_keywords(needle: str) -> None:
    """关键词存在性 sanity check，确保 T17-8 升级未误删。"""

    assert needle in builtin_prompts._STORY_FORMULA_GENERATOR
