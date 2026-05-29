"""W30-T1 subtitle_styles 项目级 FK + alembic 0019 升降级测试。

覆盖目标：
    1. alembic 0019 升降级：在 0018 baseline 上 ``upgrade head`` 后
       ``subtitle_styles`` 上多出 ``project_id`` 列与 ``ix_subtitle_styles_project_id``
       索引；``downgrade -1`` 后干净移除。
    2. 系统行（``project_id`` NULL）保持 NULL 不变，不会被 backfill。
    3. 项目级行可与系统级行同名（``(project_id, name)`` 不冲突）；不同
       project 之间的同名也允许（service 层会单独 enforce 同 project 内
       唯一）。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.core.db import Base

# 模型必须 import，确保 Base.metadata 拥有完整定义。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.compliance  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.llm  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.studio  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.subtitle  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.task  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.task_links  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import,wrong-import-position


# 0019 在 subtitle_styles 表上新增的列与索引名
NEW_COLUMN_0019: str = "project_id"
NEW_INDEX_0019: str = "ix_subtitle_styles_project_id"

# 0020 (P5 W31) 在 chapter_timeline_segments 上新增的列与索引名；
# 本测试 fixture 在 pre-0019 schema 中也要把它们一起 strip，否则 alembic
# 0019→0020 升级会与已存在的 ORM 列冲突。
NEW_COLUMNS_0020: set[str] = {"bgm_file_id", "sfx_file_id", "bgm_ducking_db"}
NEW_INDEXES_0020: set[str] = {
    "ix_chapter_timeline_segments_bgm_file_id",
    "ix_chapter_timeline_segments_sfx_file_id",
}

# 0023 (P5 W31-followup) 又在 chapter_timeline_segments 上加了 sfx_offset_ms；
# 同样需要在 pre-0019 fixture 中 strip，否则 alembic 0022→0023 会撞列。
SEGMENT_FUTURE_COLUMNS: set[str] = NEW_COLUMNS_0020 | {"sfx_offset_ms"}


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0019_schema(engine: Engine) -> None:
    """搭建 "pre-0019" 状态：建出当前完整 ORM schema，再丢掉 0019+ 引入的列与表。

    SQLite 不支持原生 DROP COLUMN with FK；这里把表复制到独立 MetaData 上
    并在复制时跳过 0019 / 0020 列与对应 FK 约束，避免污染共享 ``Base.metadata``。

    W32 (alembic 0021) 引入 ``users`` 表后，pre-0019 schema 还不应该有该表，
    否则 ``upgrade head`` 经过 0021 ``op.create_table('users', ...)`` 时与
    ``Base.metadata.create_all`` 已建出的 ``users`` 冲突（"users 已存在"）。
    """
    fresh = MetaData()
    skip_cols_subtitle = {NEW_COLUMN_0019}
    skip_cols_segment = SEGMENT_FUTURE_COLUMNS
    # pre-0019 baseline 之后才被 alembic 0021+ 创建的表，必须从 fixture 中跳过
    skip_tables: set[str] = {"users"}

    for source in Base.metadata.sorted_tables:
        if source.name in skip_tables:
            continue
        copy_target = source.to_metadata(
            fresh,
            referred_schema_fn=lambda _t, _to_schema, _ck, referred_schema: referred_schema,
        )
        if source.name == "subtitle_styles":
            _strip_columns(copy_target, skip_cols_subtitle)
        elif source.name == "chapter_timeline_segments":
            _strip_columns(copy_target, skip_cols_segment)

    fresh.create_all(bind=engine)


def _strip_columns(table: object, skip_cols: set[str]) -> None:
    """在拷贝出来的 Table 上原地剔除指定列、对应 FK 与索引。

    封装这一步是因为 0019 与 0020 都需要"复制 ORM Table → 跳过未来列"的
    同款逻辑（仅作用于不同的表 + 不同的列集）；抽出来避免把 fixture 写
    成两份 ~30 行的拷贝。
    """
    columns = getattr(table, "columns")
    constraints = getattr(table, "constraints")
    fks = getattr(table, "foreign_key_constraints")
    indexes = getattr(table, "indexes")
    for col_name in skip_cols:
        if col_name in columns:
            col = columns[col_name]
            table._columns.remove(col)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    stale_fks = [
        fk for fk in list(fks) if any(c.name in skip_cols for c in fk.columns)
    ]
    for fk in stale_fks:
        constraints.discard(fk)
    stale_indexes = [
        ix for ix in list(indexes) if any(c.name in skip_cols for c in ix.columns)
    ]
    for ix in stale_indexes:
        indexes.discard(ix)


def _stamp_version(engine: Engine, version: str) -> None:
    """将 ``alembic_version`` 表标记为指定版本号。"""
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
    """提供一个临时文件 SQLite engine。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "alembic_0019_test.db"
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
    """返回一个 alembic_version=0018、缺少 0019 schema 的临时 engine。"""
    _setup_pre_0019_schema(tmp_engine)
    _stamp_version(tmp_engine, "0018")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def _table_indexes(engine: Engine, table: str) -> set[str]:
    """返回指定表上的索引名集合。"""
    inspector = inspect(engine)
    return {idx["name"] for idx in inspector.get_indexes(table)}


# ---------------------------------------------------------------------------
# alembic 0019 升降级
# ---------------------------------------------------------------------------


def test_upgrade_head_adds_project_id_column(baseline_engine: Engine) -> None:
    """upgrade head 后必须在 subtitle_styles 上多出 project_id 列与索引。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    cols = _table_columns(baseline_engine, "subtitle_styles")
    assert NEW_COLUMN_0019 in cols, (
        f"subtitle_styles missing new column: {NEW_COLUMN_0019}"
    )

    indexes = _table_indexes(baseline_engine, "subtitle_styles")
    assert NEW_INDEX_0019 in indexes, (
        f"subtitle_styles missing index: {NEW_INDEX_0019}"
    )


def test_downgrade_removes_project_id_column(baseline_engine: Engine) -> None:
    """downgrade 到 0018 后必须干净移除 project_id 列与索引。

    原 W30 测试用 ``downgrade -1`` 假设 head==0019；W31 引入 0020 后 head 改
    变，需要显式指定 target=0018 才能回到"0019 之前"。
    """
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0018")

    cols = _table_columns(baseline_engine, "subtitle_styles")
    assert NEW_COLUMN_0019 not in cols, (
        f"{NEW_COLUMN_0019} should be removed by downgrade"
    )
    indexes = _table_indexes(baseline_engine, "subtitle_styles")
    assert NEW_INDEX_0019 not in indexes, (
        f"{NEW_INDEX_0019} should be removed by downgrade"
    )


def test_upgrade_preserves_system_rows_null(baseline_engine: Engine) -> None:
    """upgrade 到 0019 后，已存在的系统行 project_id 应为 NULL（不被 backfill）。

    本测试只验证 0019 自身的 NULL 保留语义；后续 0022 在 SQLite 上往
    ``subtitle_styles`` 加 STORED 生成列，对已有行的表 SQLite 不允许
    ALTER ADD STORED，因此测试目标显式锁在 0019。
    """
    # 在 baseline（0018，无 project_id 列）上塞一条系统行
    with baseline_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO subtitle_styles "
                "(id, name, description, language_code, format, font_family, "
                " font_fallback_chain, font_size, primary_colour, "
                " secondary_colour, outline_colour, back_colour, bold, "
                " italic, border_style, outline, shadow, alignment, "
                " margin_l, margin_r, margin_v, play_res_x, play_res_y, "
                " is_system, sort_order, created_at, updated_at) "
                "VALUES "
                "('test_system_style', 'TestSystem', '', 'zh-CN', 'ass', "
                " 'Source Han Sans CN Heavy', '[]', 60, '&H00FFFFFF', "
                " '&H00FFFFFF', '&H00000000', '&H80000000', 1, 0, 1, 3.0, "
                " 1.0, 'bottom_center', 60, 60, 200, 1080, 1920, 1, 0, "
                " '2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )

    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0019")

    with baseline_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT project_id FROM subtitle_styles "
                "WHERE id='test_system_style'"
            )
        ).scalar_one()
    assert result is None, (
        f"expected project_id NULL for system rows, got {result!r}"
    )


def test_project_scope_does_not_break_system_name(
    baseline_engine: Engine,
) -> None:
    """项目级行可以与系统级行重名（不同 (project_id, name)）。

    需要先建一条 ``projects`` 行让 FK 约束有效，再分别插系统级 + 项目级
    同名 ``DOUYIN_DEFAULT``，应能共存。
    """
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    from sqlalchemy.orm import Session

    from app.models.studio_projects import Project

    with Session(baseline_engine) as orm_session:
        proj = Project(
            id="proj-1",
            name="Demo",
            description="",
            style="modern",
        )
        orm_session.add(proj)
        orm_session.commit()

    with baseline_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO subtitle_styles "
                "(id, name, description, language_code, format, font_family, "
                " font_fallback_chain, font_size, primary_colour, "
                " secondary_colour, outline_colour, back_colour, bold, italic, "
                " border_style, outline, shadow, alignment, margin_l, margin_r, "
                " margin_v, play_res_x, play_res_y, is_system, sort_order, "
                " project_id, created_at, updated_at) "
                "VALUES "
                "('douyin_default', '抖音默认', '', 'zh-CN', 'ass', "
                " 'Source Han Sans CN Heavy', '[]', 60, '&H00FFFFFF', "
                " '&H00FFFFFF', '&H00000000', '&H80000000', 1, 0, 1, 3.0, 1.0, "
                " 'bottom_center', 60, 60, 200, 1080, 1920, 1, 0, NULL, "
                " '2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO subtitle_styles "
                "(id, name, description, language_code, format, font_family, "
                " font_fallback_chain, font_size, primary_colour, "
                " secondary_colour, outline_colour, back_colour, bold, italic, "
                " border_style, outline, shadow, alignment, margin_l, margin_r, "
                " margin_v, play_res_x, play_res_y, is_system, sort_order, "
                " project_id, created_at, updated_at) "
                "VALUES "
                "('proj1_douyin', '抖音默认', '', 'zh-CN', 'ass', "
                " 'Source Han Sans CN Heavy', '[]', 72, '&H00FFFFFF', "
                " '&H00FFFFFF', '&H00000000', '&H80000000', 1, 0, 1, 3.0, 1.0, "
                " 'bottom_center', 60, 60, 200, 1080, 1920, 0, 0, 'proj-1', "
                " '2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )

    with baseline_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, project_id FROM subtitle_styles ORDER BY id")
        ).all()
    assert len(rows) == 2
    ids = {r[0] for r in rows}
    assert ids == {"douyin_default", "proj1_douyin"}
