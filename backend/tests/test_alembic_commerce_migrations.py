"""Alembic 迁移集成测试 — 覆盖 W2/W11 新增的 6 条 revision (0002-0007)。

测试目标：

1. ``alembic upgrade head`` 在"pre-0002"状态的 SQLite 库上能成功执行，且
   生成的 schema 与 ORM 模型一致（13 张新表 + ``projects.kind`` 列）。
2. ``alembic downgrade base`` 能干净回滚至 0001（13 张新表全部消失，
   ``projects.kind`` 列消失）。
3. upgrade → downgrade → upgrade 往返后 schema 完全一致（表名/索引/外键
   集合都不变），保证迁移真正幂等。
4. 6 条 revision 在脚本目录中形成线性单 head 链：
   0001 ← 0002 ← 0003 ← 0004 ← 0005 ← 0006 ← 0007。
5. 升级 0002 后，pre-0002 即已写入的 ``projects`` 行能拿到
   ``kind='drama'`` 默认值（由 server_default + UPDATE 双保险回填）。

为了模拟"pre-0002"环境（``projects`` 没有 ``kind`` 列、且 13 张新表都
不存在），fixture 先用 ``Base.metadata`` 创建当前老表，再显式删
除 ``ix_projects_kind`` 索引和 ``projects.kind`` 列，最后把
``alembic_version`` 表的版本号设为 ``0001``。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Index, create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.core.db import Base

# 模型必须全部 import，确保 Base.metadata 拥有完整定义。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import


# === 常量：W2/W11/W17 新增的 15 张表 ===
NEW_TABLES: frozenset[str] = frozenset(
    {
        "products",
        "product_images",
        "project_product_links",
        "commerce_story_configs",
        "story_formulas",
        "story_variants",
        "story_outcomes",
        "compliance_profiles",
        "compliance_findings",
        "api_key_quotas",
        # W11-T2a (revision 0007) — pattern libraries
        "hook_patterns",
        "cta_patterns",
        "brand_archetypes",
        # W17 T17-3 (revision 0009) — voice pack + TTS cache
        "voice_packs",
        "tts_cache",
    }
)

# === 常量：每条 revision 的 down_revision 链 ===
EXPECTED_CHAIN: tuple[tuple[str, str | None], ...] = (
    ("0001", None),
    ("0002", "0001"),
    ("0003", "0002"),
    ("0004", "0003"),
    ("0005", "0004"),
    ("0006", "0005"),
    ("0007", "0006"),
    ("0008", "0007"),
    ("0009", "0008"),
)

# 每条 revision 必须显式声明的关键索引（用于 test_upgrade 的 spot check）。
EXPECTED_INDEXES: dict[str, set[str]] = {
    "projects": {"ix_projects_kind"},
    "products": {"ix_products_name", "ix_products_category"},
    "story_formulas": {"ix_story_formulas_region_category"},
    "compliance_findings": {"ix_compliance_findings_variant_severity"},
    "api_key_quotas": {"ix_api_key_quotas_is_active"},
}


def _alembic_dir() -> Path:
    """Return the absolute path to ``backend/alembic`` regardless of cwd."""
    return Path(__file__).resolve().parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """Build an Alembic ``Config`` pointed at the given SQLite URL.

    The project's ``alembic/env.py`` resolves the connection URL through
    ``app.config.settings.database_url`` and *overwrites* whatever
    ``sqlalchemy.url`` the caller supplied. We therefore must mutate the
    cached ``settings`` instance before running ``alembic.command.*``,
    which is the responsibility of the ``baseline_engine`` fixture.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0002_schema(engine: Engine) -> None:
    """Set up the 35 pre-existing tables minus ``projects.kind``.

    Steps:
    1. Copy every Table in ``Base.metadata`` (except 0009's voice_packs /
       tts_cache) onto a fresh ``MetaData``; while copying we also strip
       out the 5 FK columns added by 0009 so that ``create_all`` doesn't
       materialise them. This avoids polluting the shared ``Base.metadata``
       mapper configuration that other tests rely on.
    2. Drop the ``ix_projects_kind`` index (created by ``create_all`` because
       the live ``Project`` model declares ``index=True`` on ``kind``).
    3. Drop the ``kind`` column itself, simulating the legacy schema that
       existed before revision 0002.
    4. Drop the columns added by revision 0008 on ``shots``.
    """
    from sqlalchemy import MetaData

    fk_columns_0009: dict[str, tuple[str, ...]] = {
        "characters": ("voice_pack_id",),
        "story_variants": ("voice_pack_id", "narration_voice_pack_id"),
        "shot_dialog_lines": (
            "start_time_ms",
            "end_time_ms",
            "tts_voice_id",
            "tts_audio_file_id",
        ),
    }

    fresh = MetaData()
    for source in Base.metadata.sorted_tables:
        if source.name in NEW_TABLES:
            continue
        skip_cols = set(fk_columns_0009.get(source.name, ()))
        copy_target = source.to_metadata(fresh)
        for col_name in skip_cols:
            if col_name in copy_target.columns:
                col = copy_target.columns[col_name]
                for fk in list(col.foreign_keys):
                    if fk.constraint is not None:
                        copy_target.constraints.discard(fk.constraint)
                    copy_target.foreign_keys.discard(fk)
                copy_target._columns.remove(col)  # type: ignore[attr-defined]
        if skip_cols:
            kept: set[Index] = set()
            for ix in list(copy_target.indexes):
                referenced = {c.name for c in ix.columns}
                if not (referenced & skip_cols):
                    kept.add(ix)
            copy_target.indexes = kept

    fresh.create_all(bind=engine)

    with engine.begin() as conn:
        # SQLite 3.35+ supports both DROP INDEX IF EXISTS and ALTER TABLE
        # ... DROP COLUMN, which lets us "rewind" the projects table to
        # its pre-0002 shape without rebuilding it manually.
        conn.execute(text("DROP INDEX IF EXISTS ix_projects_kind"))
        conn.execute(text("ALTER TABLE projects DROP COLUMN kind"))
        # Cross-revision invariant: ``Base.metadata.create_all`` materialises
        # every column declared on ORM models, including columns added by
        # later migrations (0008+: shots.audio_strategy / product_focus_level).
        # We must drop them here so the subsequent ``upgrade head`` doesn't
        # collide with "duplicate column" errors. Future migrations adding
        # new shots columns must extend this drop list.
        conn.execute(text("ALTER TABLE shots DROP COLUMN audio_strategy"))
        conn.execute(text("ALTER TABLE shots DROP COLUMN product_focus_level"))


def _stamp_version(engine: Engine, version: str) -> None:
    """Insert a single row into ``alembic_version`` to mark the DB at ``version``."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": version},
        )


@pytest.fixture()
def tmp_engine() -> Iterator[Engine]:
    """Yield a synchronous SQLite engine bound to a fresh temp file.

    Uses a real file (not ``:memory:``) so multiple Alembic ``Connection``
    handles see the same data; alembic.command opens its own short-lived
    connections internally.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "alembic_test.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url, future=True)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture()
def baseline_engine(
    tmp_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Engine:
    """Return ``tmp_engine`` with the pre-0002 schema and ``alembic_version=0001``.

    Also redirects ``app.config.settings.database_url`` at the same URL so
    that ``alembic/env.py`` (which reads from settings, not from the cli
    ``--sqlalchemy.url``) targets the temp file. The monkeypatch is
    automatically reverted at end of test.
    """
    _setup_pre_0002_schema(tmp_engine)
    _stamp_version(tmp_engine, "0001")
    # env.py converts aiosqlite/aiomysql to sync; we hand it a sync URL
    # already so there is nothing to rewrite.
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


# --------------------------------------------------------------------------- #
# Test 1: alembic upgrade head adds all 10 new tables + key indexes + FKs
# --------------------------------------------------------------------------- #
def test_upgrade_head_creates_all_new_tables(baseline_engine: Engine) -> None:
    """After ``upgrade head`` the schema must include every new table.

    Also spot-checks the key indexes mandated by the spec (``BigInteger``
    column, combined indexes, etc.) and confirms a representative FK is
    declared on ``project_product_links``.
    """
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())

    # All 10 new tables present.
    missing = NEW_TABLES - tables
    assert not missing, f"missing new tables: {sorted(missing)}"

    # ``projects.kind`` was added back.
    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    assert "kind" in project_cols

    # Spot-check the spec-mandated indexes.
    for table, expected in EXPECTED_INDEXES.items():
        actual: set[str] = {
            idx["name"]
            for idx in inspector.get_indexes(table)
            if idx["name"] is not None
        }
        missing_ix = expected - actual
        assert not missing_ix, (
            f"table {table} missing indexes: {sorted(missing_ix)}, "
            f"got: {sorted(actual)}"
        )

    # Representative FK check: project_product_links → products.id (CASCADE).
    fks = inspector.get_foreign_keys("project_product_links")
    fk_targets = {
        fk["referred_table"] for fk in fks if fk["constrained_columns"]
    }
    # Should reference projects, chapters, shots, products.
    assert {"projects", "chapters", "shots", "products"} <= fk_targets


# --------------------------------------------------------------------------- #
# Test 2: alembic downgrade base removes all new tables
# --------------------------------------------------------------------------- #
def test_downgrade_base_removes_new_tables(baseline_engine: Engine) -> None:
    """After ``upgrade head`` then ``downgrade 0001`` the new schema is gone.

    Note: we downgrade to ``0001`` (not literal ``base``) because
    revision 0001 is the project's stamp baseline — going below it would
    drop the 35 pre-existing tables, which 0001 explicitly disclaims as
    out-of-scope.
    """
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())

    # None of the 10 new tables remain.
    leftover = tables & NEW_TABLES
    assert not leftover, f"new tables not removed: {sorted(leftover)}"

    # ``projects.kind`` is gone again.
    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    assert "kind" not in project_cols


# --------------------------------------------------------------------------- #
# Test 3: upgrade → downgrade → upgrade is idempotent
# --------------------------------------------------------------------------- #
def _capture_schema(engine: Engine) -> dict[str, dict[str, object]]:
    """Snapshot {table -> {tables, indexes, foreign_keys}} for diffing.

    Returns a structure that is hashable / comparable across runs:
    each new table maps to a dict with sorted, name-only views of its
    indexes and foreign keys, ignoring autogenerated artefacts that may
    differ between drivers (e.g. SQLite-internal FK names).
    """
    inspector = inspect(engine)
    snapshot: dict[str, dict[str, object]] = {}
    for table in sorted(NEW_TABLES):
        snapshot[table] = {
            "columns": sorted(
                col["name"] for col in inspector.get_columns(table)
            ),
            "indexes": sorted(
                (idx["name"], tuple(idx["column_names"]))
                for idx in inspector.get_indexes(table)
            ),
            "foreign_keys": sorted(
                (
                    fk["referred_table"],
                    tuple(fk["constrained_columns"]),
                    tuple(fk["referred_columns"]),
                )
                for fk in inspector.get_foreign_keys(table)
            ),
        }
    return snapshot


def test_roundtrip_preserves_schema(baseline_engine: Engine) -> None:
    """Schema after upgrade-then-downgrade-then-upgrade equals first upgrade."""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "head")
    snapshot_first = _capture_schema(baseline_engine)

    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    snapshot_second = _capture_schema(baseline_engine)

    assert snapshot_first == snapshot_second, (
        "schema diverged after roundtrip; "
        f"first={snapshot_first}\nsecond={snapshot_second}"
    )


# --------------------------------------------------------------------------- #
# Test 4: linear revision chain
# --------------------------------------------------------------------------- #
def test_revision_chain_is_linear() -> None:
    """The revision graph must form a single linear chain ending at 0007.

    Verifies, for every expected (rev, down_rev) pair, that:
    - the revision exists in the script directory
    - its ``down_revision`` matches the predecessor exactly
    - the resulting graph has exactly one head (no branching)
    """
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    for rev, expected_down in EXPECTED_CHAIN:
        revision = script.get_revision(rev)
        assert revision is not None, f"revision {rev} missing"
        if expected_down is None:
            assert not revision.down_revision, (
                f"{rev} should have no down_revision, "
                f"got {revision.down_revision!r}"
            )
        else:
            assert revision.down_revision == expected_down, (
                f"{rev}.down_revision should be {expected_down!r}, "
                f"got {revision.down_revision!r}"
            )

    heads = script.get_heads()
    assert list(heads) == ["0009"], f"expected single head 0009, got {heads!r}"


# --------------------------------------------------------------------------- #
# Test 5: pre-0002 row gets backfilled to kind='drama' on upgrade
# --------------------------------------------------------------------------- #
def test_pre_0002_row_backfilled_to_drama(baseline_engine: Engine) -> None:
    """A row inserted before 0002 must end up with ``kind='drama'`` after upgrade.

    Workflow:
    1. Insert a project row at the pre-0002 schema (kind column doesn't
       exist, so just supply id/name + minimum NOT NULL columns).
    2. Run ``alembic upgrade head``.
    3. Re-select the row and check ``kind='drama'`` was applied by the
       server-default + UPDATE backfill in revision 0002.
    """
    project_id = "proj-pre-0002"
    with baseline_engine.begin() as conn:
        # Insert with only the columns we know exist pre-0002. The Project
        # model includes several NOT NULL columns without server_default
        # (e.g. ``style``); we provide values for them to keep the insert
        # portable across SQLAlchemy versions.
        cols = {col["name"] for col in inspect(baseline_engine).get_columns("projects")}
        assert "kind" not in cols, "fixture should have removed kind column"
        # Build a minimal INSERT touching only NOT NULL columns without
        # defaults, plus id/name.
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, name, description, style, visual_style, seed, "
                " unify_style, progress, stats) "
                "VALUES (:id, :name, '', '真人都市', '现实', 0, "
                " 1, 0, '{}')"
            ),
            {"id": project_id, "name": "pre-0002-project"},
        )

    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    with baseline_engine.connect() as conn:
        row = conn.execute(
            text("SELECT kind FROM projects WHERE id = :id"),
            {"id": project_id},
        ).one()
    assert row.kind == "drama", f"expected kind='drama', got {row.kind!r}"


# --------------------------------------------------------------------------- #
# Defensive sanity checks for the test fixtures themselves
# --------------------------------------------------------------------------- #
def test_fixture_creates_pre_0002_state(baseline_engine: Engine) -> None:
    """Sanity: the fixture truly places the DB in pre-0002 condition."""
    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())

    # 35 pre-existing tables exist (alembic_version is the 36th, internal).
    assert "projects" in tables
    assert "alembic_version" in tables
    # None of the new tables exist yet.
    assert not (tables & NEW_TABLES), (
        f"unexpected new tables in baseline: {sorted(tables & NEW_TABLES)}"
    )
    # ``projects.kind`` should not exist yet.
    project_cols = {col["name"] for col in inspector.get_columns("projects")}
    assert "kind" not in project_cols
    # The stamp must read 0001.
    with baseline_engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert version == "0001"


def test_revision_filenames_match_chain() -> None:
    """Each revision file name encodes its revision id (``0002_*.py`` etc.)."""
    versions_dir = _alembic_dir() / "versions"
    pattern = re.compile(r"^(\d{4})_[a-z0-9_]+\.py$")
    found: set[str] = set()
    for path in versions_dir.glob("*.py"):
        match = pattern.match(path.name)
        if match:
            found.add(match.group(1))
    expected = {rev for rev, _ in EXPECTED_CHAIN}
    missing = expected - found
    assert not missing, f"missing revision files: {sorted(missing)}"
