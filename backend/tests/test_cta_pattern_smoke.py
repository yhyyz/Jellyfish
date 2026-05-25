"""Smoke tests for the W11-T2 :class:`CtaPattern` model.

Mirrors the structure of :mod:`test_hook_pattern_smoke`: each test
covers a single contract guarantee (table name, NOT NULL constraints,
indexes, defaults, instantiability). All assertions are
metadata-based to keep tests fast and avoid coupling with the Alembic
migration story.
"""

from __future__ import annotations

from app.models.cta_pattern import CtaPattern


# --- CtaPattern -----------------------------------------------------------


def test_cta_pattern_tablename() -> None:
    """``CtaPattern`` must map to the ``cta_patterns`` table."""
    assert CtaPattern.__tablename__ == "cta_patterns"


def test_cta_pattern_required_columns_are_not_nullable() -> None:
    """Required identity / classification columns must be NOT NULL."""
    columns = CtaPattern.__table__.columns
    assert columns["id"].nullable is False
    assert columns["name"].nullable is False
    assert columns["hardness"].nullable is False
    assert columns["urgency_type"].nullable is False


def test_cta_pattern_hardness_is_indexed() -> None:
    """``hardness`` is indexed for UI filtering by soft/medium/hard."""
    assert CtaPattern.__table__.columns["hardness"].index is True


def test_cta_pattern_urgency_type_is_indexed() -> None:
    """``urgency_type`` is indexed for UI filtering by driver mechanism."""
    assert CtaPattern.__table__.columns["urgency_type"].index is True


def test_cta_pattern_is_system_default_true() -> None:
    """Both ORM default and ``server_default`` for ``is_system`` resolve to True."""
    column = CtaPattern.__table__.columns["is_system"]
    assert column.default is not None
    assert column.default.arg is True
    assert column.server_default is not None
    server_default_text = getattr(
        column.server_default.arg, "text", column.server_default.arg
    )
    assert server_default_text == "1"


def test_cta_pattern_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise."""
    pattern = CtaPattern(
        id="scarcity_cta",
        name="稀缺紧迫",
        hardness="hard",
        urgency_type="scarcity",
    )
    assert pattern.id == "scarcity_cta"
    assert pattern.name == "稀缺紧迫"
    assert pattern.hardness == "hard"
    assert pattern.urgency_type == "scarcity"
