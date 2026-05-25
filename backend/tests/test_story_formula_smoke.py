"""Smoke tests for story-driven commerce W2-T2 models.

Verifies the three new ORM classes added by W2-T2 before the matching
Alembic migration (W2-T5) is generated:

* :class:`app.models.story_formula.StoryFormula`
* :class:`app.models.story_formula.StoryVariant`
* :class:`app.models.story_formula.StoryOutcome`

Each test focuses on a single contract guarantee (table name, foreign
keys, indexes, instantiability) so a regression points directly at the
broken declaration. The tests deliberately avoid hitting the real
database -- they introspect SQLAlchemy table metadata only -- which
keeps them fast and decoupled from the Alembic migration story.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer

from app.models.story_formula import StoryFormula, StoryVariant, StoryOutcome
from app.models.types import FormulaRegion, Platform, StoryVariantStatus


# --- StoryFormula ---------------------------------------------------------


def test_story_formula_tablename() -> None:
    """``StoryFormula`` must map to the ``story_formulas`` table."""
    assert StoryFormula.__tablename__ == "story_formulas"


def test_story_formula_prompt_template_fk() -> None:
    """``prompt_template_id`` is a NOT NULL FK to ``prompt_templates.id`` with RESTRICT.

    RESTRICT is required so deleting a referenced template surfaces an
    error rather than silently orphaning the formula.
    """
    column = StoryFormula.__table__.columns["prompt_template_id"]
    assert column.nullable is False
    fks = list(column.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "prompt_templates"
    assert fks[0].column.name == "id"
    assert fks[0].ondelete == "RESTRICT"


def test_story_formula_region_category_combined_index() -> None:
    """A combined index on (region, category) must exist for filter queries."""
    indexes = {idx.name: idx for idx in StoryFormula.__table__.indexes}
    assert "ix_story_formulas_region_category" in indexes
    columns = [c.name for c in indexes["ix_story_formulas_region_category"].columns]
    assert columns == ["region", "category"]


def test_story_formula_sort_order_is_indexed() -> None:
    """``sort_order`` is indexed so UI ordering does not table-scan."""
    column = StoryFormula.__table__.columns["sort_order"]
    assert column.index is True


def test_story_formula_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise.

    ``StoryFormula`` is system-managed and most columns carry Python-side
    defaults; only ``id`` / ``name`` / ``prompt_template_id`` are required
    from a caller's perspective.
    """
    formula = StoryFormula(
        id="underdog_triumph",
        name="凡人逆袭",
        prompt_template_id="tpl-formula-001",
    )
    assert formula.id == "underdog_triumph"
    assert formula.name == "凡人逆袭"
    assert formula.prompt_template_id == "tpl-formula-001"


def test_story_formula_region_default_is_cn() -> None:
    """Both ORM default and server_default for ``region`` resolve to ``cn``."""
    column = StoryFormula.__table__.columns["region"]
    assert column.default is not None
    assert column.default.arg == FormulaRegion.cn.value
    assert column.server_default is not None
    server_default_text = getattr(column.server_default.arg, "text", column.server_default.arg)
    assert server_default_text == FormulaRegion.cn.value


# --- StoryVariant ---------------------------------------------------------


def test_story_variant_tablename() -> None:
    """``StoryVariant`` must map to the ``story_variants`` table."""
    assert StoryVariant.__tablename__ == "story_variants"


def test_story_variant_foreign_keys() -> None:
    """``StoryVariant`` exposes FKs to ``projects`` / ``chapters`` / ``story_formulas``.

    * ``project_id`` and ``chapter_id`` use CASCADE (drop variants with parent).
    * ``formula_id`` uses RESTRICT to protect history of past variants.
    """
    columns = StoryVariant.__table__.columns

    project_fks = list(columns["project_id"].foreign_keys)
    assert len(project_fks) == 1
    assert project_fks[0].column.table.name == "projects"
    assert project_fks[0].ondelete == "CASCADE"

    chapter_fks = list(columns["chapter_id"].foreign_keys)
    assert len(chapter_fks) == 1
    assert chapter_fks[0].column.table.name == "chapters"
    assert chapter_fks[0].ondelete == "CASCADE"

    formula_fks = list(columns["formula_id"].foreign_keys)
    assert len(formula_fks) == 1
    assert formula_fks[0].column.table.name == "story_formulas"
    assert formula_fks[0].ondelete == "RESTRICT"


def test_story_variant_status_is_indexed_and_defaults_draft() -> None:
    """``status`` column is indexed and defaults to ``StoryVariantStatus.draft``."""
    column = StoryVariant.__table__.columns["status"]
    assert column.index is True
    assert column.default is not None
    assert column.default.arg == StoryVariantStatus.draft.value
    assert column.server_default is not None
    server_default_text = getattr(column.server_default.arg, "text", column.server_default.arg)
    assert server_default_text == StoryVariantStatus.draft.value


def test_story_variant_p2_columns_are_nullable() -> None:
    """``hook_pattern_id`` / ``cta_pattern_id`` / ``archetype`` are P2-only and nullable."""
    columns = StoryVariant.__table__.columns
    assert columns["hook_pattern_id"].nullable is True
    assert columns["cta_pattern_id"].nullable is True
    assert columns["archetype"].nullable is True


def test_story_variant_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise."""
    variant = StoryVariant(
        id="var-001",
        project_id="proj-1",
        chapter_id="chap-1",
        formula_id="underdog_triumph",
    )
    assert variant.id == "var-001"
    assert variant.project_id == "proj-1"
    assert variant.chapter_id == "chap-1"
    assert variant.formula_id == "underdog_triumph"


# --- StoryOutcome ---------------------------------------------------------


def test_story_outcome_tablename() -> None:
    """``StoryOutcome`` must map to the ``story_outcomes`` table."""
    assert StoryOutcome.__tablename__ == "story_outcomes"


def test_story_outcome_variant_fk_cascades() -> None:
    """``variant_id`` is a CASCADE FK to ``story_variants.id``."""
    column = StoryOutcome.__table__.columns["variant_id"]
    assert column.nullable is False
    fks = list(column.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "story_variants"
    assert fks[0].column.name == "id"
    assert fks[0].ondelete == "CASCADE"


def test_story_outcome_plays_uses_bigint() -> None:
    """``plays`` MUST be ``BigInteger`` to survive viral 2^31+ counts.

    A regression to plain ``Integer`` would silently corrupt high-traffic
    rows on MySQL/PostgreSQL, which is why this is asserted explicitly.
    Note: ``BigInteger`` subclasses ``Integer`` in SQLAlchemy, so we
    additionally check the column type's class identity to reject a
    silent downgrade.
    """
    column = StoryOutcome.__table__.columns["plays"]
    assert isinstance(column.type, BigInteger)
    # Defensive: ``BigInteger`` is not interchangeable with ``Integer`` here.
    assert column.type.__class__ is BigInteger
    assert column.type.__class__ is not Integer


def test_story_outcome_completion_rates_are_nullable() -> None:
    """3s / full completion rates must allow NULL when not reported."""
    columns = StoryOutcome.__table__.columns
    assert columns["completion_rate_3s"].nullable is True
    assert columns["completion_rate_full"].nullable is True


def test_story_outcome_platform_is_indexed_and_defaults_douyin() -> None:
    """``platform`` is indexed and defaults to ``Platform.douyin`` for CN-first launch."""
    column = StoryOutcome.__table__.columns["platform"]
    assert column.index is True
    assert column.default is not None
    assert column.default.arg == Platform.douyin.value
    assert column.server_default is not None
    server_default_text = getattr(column.server_default.arg, "text", column.server_default.arg)
    assert server_default_text == Platform.douyin.value


def test_story_outcome_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise.

    ``recorded_at`` has no default at the model layer (callers must supply
    a meaningful business window), so it is a required kwarg.
    """
    from datetime import datetime, timezone

    outcome = StoryOutcome(
        variant_id="var-001",
        recorded_at=datetime(2025, 5, 25, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert outcome.variant_id == "var-001"
    assert outcome.recorded_at.year == 2025
