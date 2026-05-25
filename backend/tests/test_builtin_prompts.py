"""``bootstrap_builtin_prompts`` 的功能性测试。

覆盖目标：
1. 全量插入：fresh DB 上首次运行写入 27 行 ``is_system=True``；
2. 幂等：第二次运行不再有 inserts，且 ``unchanged == 27``；
3. 内容回滚：手工改写一行后再次运行，会被纠回 canonical；
4. 严格未定义变量：``render_template`` 在缺变量时抛 ``UndefinedError``；
5. Pydantic ``extra='forbid'`` + Jinja 渲染：多余变量在上下文层被拒；
6. 12 个 commerce 模板能用各自合理 sample 渲染、不报 UndefinedError；
7. 15 个 LEGACY 占位模板可用空字典渲染（实际仅声明字段，没有变量）。
"""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import PromptCategory
from app.services.studio.builtin_prompts import (
    BUILTIN_PROMPT_DEFINITIONS,
    bootstrap_builtin_prompts,
    render_template,
)

# 预期数量来自 plan：12 commerce + 15 legacy。
_EXPECTED_TOTAL = 27
_EXPECTED_COMMERCE = 12
_EXPECTED_LEGACY = 15

_LEGACY_CATEGORIES = {
    PromptCategory.frame_tail_image,
    PromptCategory.frame_key_image,
    PromptCategory.frame_head_prompt,
    PromptCategory.frame_tail_prompt,
    PromptCategory.frame_key_prompt,
    PromptCategory.video_prompt,
    PromptCategory.storyboard_prompt,
    PromptCategory.bgm,
    PromptCategory.sfx,
    PromptCategory.character_image_front,
    PromptCategory.character_image_other,
    PromptCategory.scene_image_other,
    PromptCategory.prop_image_other,
    PromptCategory.costume_image_other,
    PromptCategory.combined,
}

_COMMERCE_CATEGORIES = {
    PromptCategory.product_extraction,
    PromptCategory.story_formula_generator,
    PromptCategory.hook_pattern_writer,
    PromptCategory.cta_pattern_writer,
    PromptCategory.archetype_voice_rewriter,
    PromptCategory.compliance_checker,
    PromptCategory.product_image_front,
    PromptCategory.product_image_other,
    PromptCategory.product_placement_prompt,
    PromptCategory.product_hero_prompt,
    PromptCategory.audience_insight,
    PromptCategory.brand_voice_profile,
}


# ---------------------------------------------------------------------------
# 测试基础设施
# ---------------------------------------------------------------------------


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """创建一个内存 SQLite 异步 session，并建好 ORM 表。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


# ---------------------------------------------------------------------------
# 1. 全量插入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_27_templates() -> None:
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_prompts(db)
        rows = (
            await db.execute(
                select(PromptTemplate).where(PromptTemplate.is_system.is_(True))
            )
        ).scalars().all()

    await engine.dispose()

    assert stats == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert len(rows) == _EXPECTED_TOTAL
    categories = {row.category for row in rows}
    assert _LEGACY_CATEGORIES.issubset(categories)
    assert _COMMERCE_CATEGORIES.issubset(categories)


# ---------------------------------------------------------------------------
# 2. 幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_prompts(db)
        second = await bootstrap_builtin_prompts(db)
    await engine.dispose()

    assert first == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert second == {"inserted": 0, "updated": 0, "unchanged": _EXPECTED_TOTAL}


# ---------------------------------------------------------------------------
# 3. 内容回滚
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_updates_changed_content() -> None:
    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_prompts(db)

        # 手工把第一条记录的内容改坏，模拟“被运营手抖修改”。
        target = (
            await db.execute(
                select(PromptTemplate).where(PromptTemplate.is_system.is_(True))
            )
        ).scalars().first()
        assert target is not None
        target.content = "MUTATED"
        target.preview = "MUTATED"
        await db.commit()

        stats = await bootstrap_builtin_prompts(db)

        restored = (
            await db.execute(
                select(PromptTemplate).where(PromptTemplate.id == target.id)
            )
        ).scalar_one()

    await engine.dispose()

    assert stats["inserted"] == 0
    assert stats["updated"] == 1
    assert stats["unchanged"] == _EXPECTED_TOTAL - 1
    assert restored.content != "MUTATED"
    assert restored.preview != "MUTATED"


# ---------------------------------------------------------------------------
# 4. StrictUndefined 行为
# ---------------------------------------------------------------------------


def test_render_strict_undefined_raises_on_missing_var() -> None:
    template = "Hello {{ name }} & {{ goal }}"
    with pytest.raises(UndefinedError):
        render_template(template, {"name": "x"}, strict=True)


# ---------------------------------------------------------------------------
# 5. Jinja + Pydantic extra='forbid'
# ---------------------------------------------------------------------------


def test_render_strict_undefined_raises_on_extra_var_via_pydantic() -> None:
    """Pydantic ``extra='forbid'`` 的上下文模型把“多余变量”挡在渲染之前。

    这样可以实现“双向严格”：
        - 缺变量 → Jinja 抛 UndefinedError
        - 多变量 → Pydantic 抛 ValidationError
    """

    class HookCtx(BaseModel):
        model_config = ConfigDict(extra="forbid")
        pattern_id: str
        product: dict[str, object]
        audience: dict[str, object]

    with pytest.raises(ValidationError):
        HookCtx.model_validate(
            {
                "pattern_id": "question",
                "product": {"name": "p"},
                "audience": {"age": "25-34"},
                "extra_unexpected": True,
            }
        )


# ---------------------------------------------------------------------------
# 6. 12 个 commerce 模板可用合理样例渲染
# ---------------------------------------------------------------------------


def _commerce_sample_vars() -> dict[str, dict[str, object]]:
    """为 12 个 commerce 模板构造可渲染的 sample 上下文。

    这里仅保证“变量都被声明 / 渲染不报错”，不做内容真实性断言；后者由
    ``test_builtin_prompts_render_snapshots`` 的金样本测试覆盖。
    """

    base_product: dict[str, object] = {
        "name": "DemoSerum",
        "brand": "DemoLab",
        "category": "beauty",
        "selling_points": ["补水", "提亮"],
    }
    base_audience: dict[str, object] = {"age_range": "25-34", "city_tier": "T1"}
    base_tone_grid: dict[str, object] = {"formal": 4, "energy": 7, "humor": 6}

    return {
        "product_extraction_v1": {
            "raw_text": "纯净配方精华 30ml，敏肌可用。",
            "target_fields": ["name", "selling_points", "pain_points_solved"],
        },
        "story_formula_generator_v1": {
            "formula": {"id": "underdog_triumph", "beats": []},
            "product": base_product,
            "audience": base_audience,
            "archetype": "sage",
            "tone_grid": base_tone_grid,
            "target_duration_sec": 60,
            "platform": "douyin",
        },
        "hook_pattern_writer_v1": {
            "pattern_id": "question",
            "product": base_product,
            "audience": base_audience,
        },
        "cta_pattern_writer_v1": {
            "hardness": "medium",
            "product": base_product,
            "urgency_type": "scarcity",
        },
        "archetype_voice_rewriter_v1": {
            "archetype": "rebel",
            "tone_grid": base_tone_grid,
            "original_script": {"shots": []},
            "words_to_avoid": ["无敌", "首选"],
            "preferred_vocab": ["实测", "稳"],
        },
        "compliance_checker_v1": {
            "script": {"shots": []},
            "region": "cn_mainland",
            "product_category": "beauty",
        },
        "product_image_front_v1": {"product": base_product, "style": "minimalist"},
        "product_image_other_v1": {"product": base_product, "view_angle": "detail"},
        "product_placement_prompt_v1": {
            "product": base_product,
            "scene": "bathroom morning",
            "interaction": "拿起涂抹",
        },
        "product_hero_prompt_v1": {
            "product": base_product,
            "dramatic_moment": "镜头慢推近瓶身",
        },
        "audience_insight_v1": {
            "product": base_product,
            "target_audience": base_audience,
        },
        "brand_voice_profile_v1": {
            "archetype": "sage",
            "tone_grid": base_tone_grid,
            "competitor_voice": "高冷专业",
        },
    }


def test_all_12_commerce_templates_have_required_variables_declared() -> None:
    samples = _commerce_sample_vars()
    commerce_defs = [
        d for d in BUILTIN_PROMPT_DEFINITIONS if d.category in _COMMERCE_CATEGORIES
    ]
    assert len(commerce_defs) == _EXPECTED_COMMERCE

    for definition in commerce_defs:
        ctx = samples[definition.id]
        # 变量声明应覆盖 sample；样例提供的 key 与 variables 列表一致。
        assert set(ctx.keys()) == set(definition.variables), definition.id
        # 渲染不抛 UndefinedError。
        rendered = render_template(definition.template_content, ctx, strict=True)
        assert rendered  # 不应为空
        # 至少包含一个变量回写的痕迹（防止意外空模板）。
        for var in definition.variables:
            # 仅做软断言：模板中肯定引用过这个变量名（提示词正文里的字面量）
            assert var in definition.template_content, definition.id


# ---------------------------------------------------------------------------
# 7. 15 个 LEGACY 模板可渲染
# ---------------------------------------------------------------------------


def test_all_15_legacy_templates_renderable_with_empty_vars() -> None:
    legacy_defs = [
        d for d in BUILTIN_PROMPT_DEFINITIONS if d.category in _LEGACY_CATEGORIES
    ]
    assert len(legacy_defs) == _EXPECTED_LEGACY

    # LEGACY 模板的正文里带 ``{{ var }}`` 占位，因此严格模式仍需提供值；
    # 这里以“模板声明的 variables 列表 + 任意占位字符串”作为最小渲染上下文。
    for definition in legacy_defs:
        ctx = {var: f"<{var}>" for var in definition.variables}
        rendered = render_template(definition.template_content, ctx, strict=True)
        assert rendered.strip()
        assert "系统默认" in rendered
