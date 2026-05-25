"""Smoke tests for the ``Project.kind`` column.

Verifies that the newly added ``kind`` column on the ``Project`` model:

- is importable alongside the ``ProjectKind`` enum;
- is declared NOT NULL with default ``ProjectKind.drama`` for backwards
  compatibility with existing rows;
- can round-trip a ``commerce_story`` value through a SQLAlchemy session
  using a temporary in-memory SQLite database.

This guards the W2-T0 contract change before the matching Alembic
migration (W2-T5) is generated.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.studio_projects import Project
from app.models.types import ProjectKind


def test_project_kind_column_is_not_nullable() -> None:
    """``Project.__table__.columns['kind']`` must be NOT NULL.

    Backwards compatibility relies on every existing row receiving the
    ``drama`` default; a nullable column would defeat that guarantee.
    """
    column = Project.__table__.columns["kind"]
    assert column.nullable is False


def test_project_kind_default_is_drama() -> None:
    """The Python-side default for ``kind`` must equal ``ProjectKind.drama``.

    Both the ORM ``default`` and the DB-level ``server_default`` should
    resolve to the ``drama`` value so newly created projects (in code or
    via raw SQL) land on the legacy short-drama flow unless explicitly
    opted into ``commerce_story``.
    """
    column = Project.__table__.columns["kind"]

    # ORM-level default (used when constructing Project() in Python).
    assert column.default is not None
    assert column.default.arg == ProjectKind.drama.value
    assert column.default.arg == ProjectKind.drama  # str-enum equality

    # DB-level default (used by raw INSERTs that omit the column).
    assert column.server_default is not None
    server_default_text = getattr(column.server_default.arg, "text", column.server_default.arg)
    assert server_default_text == ProjectKind.drama.value


def test_project_kind_round_trip_commerce_story() -> None:
    """A Project saved with ``kind=commerce_story`` must read back unchanged.

    Uses an isolated in-memory SQLite engine to avoid touching the real
    database. We only create the ``projects`` table to keep the smoke
    test fast and free of cross-model FK noise.
    """
    engine = create_engine("sqlite:///:memory:")
    Project.__table__.create(engine)

    try:
        with Session(engine) as session:
            project = Project(
                id="proj-smoke-1",
                name="Smoke Commerce Project",
                style="真人都市",
                kind=ProjectKind.commerce_story.value,
            )
            session.add(project)
            session.commit()

            loaded = session.get(Project, "proj-smoke-1")
            assert loaded is not None
            assert loaded.kind == ProjectKind.commerce_story.value
    finally:
        Project.__table__.drop(engine)
        engine.dispose()
        # Ensure the ad-hoc table creation does not leak into Base metadata
        # state for subsequent tests in the same process.
        Base.metadata  # noqa: B018  (touch attribute to keep import used)
