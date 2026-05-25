"""Smoke tests for the W11-T2 :class:`BrandArchetype` model.

Mirrors the structure of :mod:`test_hook_pattern_smoke` /
:mod:`test_cta_pattern_smoke`: each test covers a single contract
guarantee (table name, NOT NULL constraints, indexes, defaults,
instantiability). All assertions are metadata-based to keep tests fast
and avoid coupling with the Alembic migration story.
"""

from __future__ import annotations

from app.models.brand_archetype import BrandArchetype


# --- BrandArchetype -------------------------------------------------------


def test_brand_archetype_tablename() -> None:
    """``BrandArchetype`` must map to the ``brand_archetypes`` table."""
    assert BrandArchetype.__tablename__ == "brand_archetypes"


def test_brand_archetype_required_columns_are_not_nullable() -> None:
    """Required identity / display columns must be NOT NULL."""
    columns = BrandArchetype.__table__.columns
    assert columns["id"].nullable is False
    assert columns["name"].nullable is False
    assert columns["name_zh"].nullable is False


def test_brand_archetype_sort_order_is_indexed() -> None:
    """``sort_order`` is indexed so UI ordering does not table-scan."""
    assert BrandArchetype.__table__.columns["sort_order"].index is True


def test_brand_archetype_is_system_default_true() -> None:
    """Both ORM default and ``server_default`` for ``is_system`` resolve to True."""
    column = BrandArchetype.__table__.columns["is_system"]
    assert column.default is not None
    assert column.default.arg is True
    assert column.server_default is not None
    server_default_text = getattr(
        column.server_default.arg, "text", column.server_default.arg
    )
    assert server_default_text == "1"


def test_brand_archetype_construct_with_required_only() -> None:
    """Constructing with required-only kwargs should not raise."""
    archetype = BrandArchetype(
        id="sage",
        name="Sage",
        name_zh="智者",
    )
    assert archetype.id == "sage"
    assert archetype.name == "Sage"
    assert archetype.name_zh == "智者"


def test_brand_archetype_id_is_primary_key() -> None:
    """``id`` must be the primary key, since it doubles as enum business key."""
    assert BrandArchetype.__table__.columns["id"].primary_key is True


def test_brand_archetype_speech_patterns_column_is_json() -> None:
    """``speech_patterns`` must be JSON to store ``{do: [...], dont: [...]}``."""
    column = BrandArchetype.__table__.columns["speech_patterns"]
    # SQLAlchemy's JSON type compiles differently per dialect, but
    # type_class identity is stable and is what we want to assert.
    type_name = column.type.__class__.__name__
    assert type_name in {"JSON", "JSONB"}
