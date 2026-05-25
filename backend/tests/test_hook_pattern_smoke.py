"""Smoke tests for the W11-T2 :class:`HookPattern` model.

Verifies the new ORM class added by W11-T2 before the matching Alembic
migration (0007) is applied to a real database. Each test focuses on a
single contract guarantee (table name, column nullability, indexes,
instantiability) so a regression points directly at the broken
declaration. The tests deliberately avoid hitting the real database --
they introspect SQLAlchemy table metadata only -- which keeps them fast
and decoupled from the migration story.
"""

from __future__ import annotations

from app.models.hook_pattern import HookPattern


# --- HookPattern ----------------------------------------------------------


def test_hook_pattern_tablename() -> None:
    """``HookPattern`` must map to the ``hook_patterns`` table."""
    assert HookPattern.__tablename__ == "hook_patterns"


def test_hook_pattern_required_columns_are_not_nullable() -> None:
    """Required identity / classification columns must be NOT NULL."""
    columns = HookPattern.__table__.columns
    assert columns["id"].nullable is False
    assert columns["name"].nullable is False
    assert columns["pattern_type"].nullable is False


def test_hook_pattern_pattern_type_is_indexed() -> None:
    """``pattern_type`` is indexed for UI list filtering by hook category."""
    assert HookPattern.__table__.columns["pattern_type"].index is True


def test_hook_pattern_sort_order_is_indexed() -> None:
    """``sort_order`` is indexed so UI ordering does not table-scan."""
    assert HookPattern.__table__.columns["sort_order"].index is True


def test_hook_pattern_is_system_default_true() -> None:
    """Both ORM default and ``server_default`` for ``is_system`` resolve to True."""
    column = HookPattern.__table__.columns["is_system"]
    assert column.default is not None
    assert column.default.arg is True
    assert column.server_default is not None
    server_default_text = getattr(
        column.server_default.arg, "text", column.server_default.arg
    )
    assert server_default_text == "1"


def test_hook_pattern_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise.

    Most columns carry Python-side defaults; only ``id`` / ``name`` /
    ``pattern_type`` are required from a caller's perspective.
    """
    pattern = HookPattern(
        id="question_hook",
        name="问句钩子",
        pattern_type="question",
    )
    assert pattern.id == "question_hook"
    assert pattern.name == "问句钩子"
    assert pattern.pattern_type == "question"
