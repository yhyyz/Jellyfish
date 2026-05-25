"""``bootstrap_builtin_story_formulas`` 与内置 6 条公式定义的功能性测试（W3-T2）。

测试目标：

1. 启动时从空库写入全部 6 条公式（``is_system=True``）。
2. 二次调用幂等（``unchanged == 6``）。
3. 各公式 beat 时长之和 ≈ ``typical_duration_sec``（± 10s）。
4. ``family_conflict`` 必带 ``family_conflict_compliance`` 风险标记。
5. 全部公式引用有效的 prompt_template_id（与 W3-T1 的注册一致）。
6. 全部公式至少 3 个 avoid_cases（合规自保）。
7. 全部公式的 typical_shot_count 在合理区间 [2, 10]。
8. 全部公式的 sample_dialog 长度 ≥ 150 字（足够支撑 LLM 学习）。
9. 全部公式 risk_flags 仅使用已知词汇表（拒绝拼写漂移）。

测试 DB 通过 SQLite ``:memory:`` 异步引擎构建，与项目其它 service 测试保持
一致；并在调用 ``bootstrap_builtin_story_formulas`` 之前预先插入一条 id 为
``story_formula_generator_v1`` 的 ``PromptTemplate`` 占位行，以满足
``story_formulas.prompt_template_id`` 外键约束（避免在测试里耦合
W3-T1 的 ``bootstrap_builtin_prompts`` 真实数据）。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base

# 必须 import 全部模型，确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.models.story_formula import StoryFormula
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import PromptCategory
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_DEFINITIONS,
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    KNOWN_RISK_FLAGS,
    bootstrap_builtin_story_formulas,
)


EXPECTED_FORMULA_IDS: frozenset[str] = frozenset(
    {
        "underdog_triumph",
        "contrast_surprise",
        "workplace_hero",
        "family_conflict",
        "mystery_twist",
        "time_travel",
    }
)


async def _build_session() -> tuple[AsyncSession, object]:
    """构建一次性 SQLite 异步会话；同时预置 prompt_templates 占位行。

    通过把 stub PromptTemplate 写在 fixture 中，我们：
    - 让本测试文件不依赖 W3-T1 的 ``bootstrap_builtin_prompts`` 真实实现
      （后者的种子数据未来可能演进）；
    - 让 ``story_formulas.prompt_template_id`` 上的 ``ON DELETE RESTRICT``
      外键在测试中也是真实生效的，能复现“启动顺序坏了”这一边界。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db = session_local()
    stub = PromptTemplate(
        id=BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
        category=PromptCategory.story_formula_generator,
        name="stub-template-for-test",
        preview="",
        content="",
        variables=[],
        is_default=False,
        is_system=True,
    )
    db.add(stub)
    await db.commit()
    return db, engine


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_6_formulas() -> None:
    """新库 -> 6 条 ``is_system=True`` 行写入；ID 集合等于约定集合。"""
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_story_formulas(db)

        assert stats == {"inserted": 6, "updated": 0, "unchanged": 0}

        rows = (await db.execute(select(StoryFormula))).scalars().all()
        assert len(rows) == 6
        assert {row.id for row in rows} == EXPECTED_FORMULA_IDS
        for row in rows:
            assert row.is_system is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    """连调两次：第一次全部 inserted，第二次全部 unchanged。"""
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_story_formulas(db)
        second = await bootstrap_builtin_story_formulas(db)

        assert first == {"inserted": 6, "updated": 0, "unchanged": 0}
        assert second == {"inserted": 0, "updated": 0, "unchanged": 6}

        rows = (await db.execute(select(StoryFormula))).scalars().all()
        assert len(rows) == 6
    await engine.dispose()


def test_each_formula_total_beat_duration_matches_typical_duration() -> None:
    """sum(beat.duration_sec) ≈ typical_duration_sec（± 10s）。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        total = sum(beat.duration_sec for beat in definition.beats)
        delta = abs(total - definition.typical_duration_sec)
        assert delta <= 10, (
            f"formula '{definition.id}' beat sum {total}s vs "
            f"typical {definition.typical_duration_sec}s exceeds ±10s"
        )


def test_family_conflict_has_mandatory_risk_flag() -> None:
    """``family_conflict`` 必须显式声明 ``family_conflict_compliance``。"""
    family = next(d for d in BUILTIN_FORMULA_DEFINITIONS if d.id == "family_conflict")
    assert "family_conflict_compliance" in family.risk_flags


def test_all_formulas_reference_valid_prompt_template_id() -> None:
    """6 条公式全部引用同一个内置模板 ID（与 W3-T1 注册保持一致）。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        assert (
            definition.prompt_template_id == BUILTIN_FORMULA_PROMPT_TEMPLATE_ID
        ), f"formula '{definition.id}' references unexpected template id"


def test_all_formulas_have_avoid_cases() -> None:
    """每条公式至少给出 3 条 avoid_cases，作为合规自保 baseline。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        assert len(definition.avoid_cases) >= 3, (
            f"formula '{definition.id}' has only "
            f"{len(definition.avoid_cases)} avoid_cases (need >= 3)"
        )


def test_each_formula_typical_shot_count_in_reasonable_range() -> None:
    """typical_shot_count ∈ [2, 10]，避免极短或失控镜头数。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        assert 2 <= definition.typical_shot_count <= 10, (
            f"formula '{definition.id}' typical_shot_count "
            f"{definition.typical_shot_count} out of [2, 10]"
        )


def test_sample_dialog_is_substantial() -> None:
    """每条 sample_dialog 至少 150 字符，确保模板可被 LLM 充分学习。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        assert len(definition.sample_dialog) >= 150, (
            f"formula '{definition.id}' sample_dialog only "
            f"{len(definition.sample_dialog)} chars (need >= 150)"
        )


def test_risk_flags_only_use_known_vocabulary() -> None:
    """所有 risk_flags 必须是 ``KNOWN_RISK_FLAGS`` 子集。"""
    for definition in BUILTIN_FORMULA_DEFINITIONS:
        unknown = set(definition.risk_flags) - KNOWN_RISK_FLAGS
        assert not unknown, (
            f"formula '{definition.id}' uses unknown risk flags {sorted(unknown)}; "
            f"vocabulary: {sorted(KNOWN_RISK_FLAGS)}"
        )
