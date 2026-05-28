"""W31-T1 chapter_timeline_segments BGM/SFX/ducking 字段 + alembic 0020 升降级测试。

覆盖目标：
    1. alembic 0020 升降级：在 0019 baseline 上 ``upgrade head`` 后
       ``chapter_timeline_segments`` 上多出 ``bgm_file_id`` / ``sfx_file_id``
       / ``bgm_ducking_db`` 三列与对应索引；``downgrade -1`` 后干净移除。
    2. 已存在的 segment 行升级后 ``bgm_file_id`` / ``sfx_file_id`` 默认 NULL，
       ``bgm_ducking_db`` 默认 ``-12.0``（不被 backfill）。
    3. ORM 写入读出 round-trip：写 BGM/SFX file_id 与自定义 ducking_db，
       重新查询应保持一致。
"""

# pylint: disable=invalid-name,duplicate-code

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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


NEW_COLUMNS_0020: set[str] = {"bgm_file_id", "sfx_file_id", "bgm_ducking_db"}
NEW_INDEXES_0020: set[str] = {
    "ix_chapter_timeline_segments_bgm_file_id",
    "ix_chapter_timeline_segments_sfx_file_id",
}


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0020_schema(engine: Engine) -> None:
    """搭建 "pre-0020" 状态：建出当前完整 ORM schema，再丢掉 0020 引入的列。

    SQLite 不支持原生 DROP COLUMN with FK；这里把表复制到独立 MetaData 上
    并在复制时跳过 0020 列与对应 FK 约束，避免污染共享 ``Base.metadata``。
    """
    fresh = MetaData()
    skip_cols = NEW_COLUMNS_0020

    for source in Base.metadata.sorted_tables:
        copy_target = source.to_metadata(
            fresh,
            referred_schema_fn=lambda _t, _to_schema, _ck, referred_schema: referred_schema,
        )
        if source.name == "chapter_timeline_segments":
            for col_name in skip_cols:
                if col_name in copy_target.columns:
                    col = copy_target.columns[col_name]
                    copy_target._columns.remove(col)  # type: ignore[attr-defined]  # pylint: disable=protected-access
            stale_fks = [
                fk
                for fk in list(copy_target.foreign_key_constraints)
                if any(c.name in skip_cols for c in fk.columns)
            ]
            for fk in stale_fks:
                copy_target.constraints.discard(fk)
            stale_indexes = [
                ix
                for ix in list(copy_target.indexes)
                if any(c.name in skip_cols for c in ix.columns)
            ]
            for ix in stale_indexes:
                copy_target.indexes.discard(ix)

    fresh.create_all(bind=engine)


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
        db_path = Path(tmp_dir) / "alembic_0020_test.db"
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
    """返回一个 alembic_version=0019、缺少 0020 schema 的临时 engine。"""
    _setup_pre_0020_schema(tmp_engine)
    _stamp_version(tmp_engine, "0019")
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
# alembic 0020 升降级
# ---------------------------------------------------------------------------


def test_upgrade_head_adds_bgm_sfx_ducking_columns(baseline_engine: Engine) -> None:
    """upgrade head 后必须在 chapter_timeline_segments 上多出 BGM/SFX/ducking 三列。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    cols = _table_columns(baseline_engine, "chapter_timeline_segments")
    missing = NEW_COLUMNS_0020 - cols
    assert not missing, f"chapter_timeline_segments missing new columns: {missing}"

    indexes = _table_indexes(baseline_engine, "chapter_timeline_segments")
    missing_idx = NEW_INDEXES_0020 - indexes
    assert not missing_idx, (
        f"chapter_timeline_segments missing indexes: {missing_idx}"
    )


def test_downgrade_removes_bgm_sfx_ducking_columns(baseline_engine: Engine) -> None:
    """downgrade -1 (head 0020 -> 0019) 后必须干净移除三列与索引。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")

    cols = _table_columns(baseline_engine, "chapter_timeline_segments")
    leaked = NEW_COLUMNS_0020 & cols
    assert not leaked, f"columns should be removed by downgrade: {leaked}"

    indexes = _table_indexes(baseline_engine, "chapter_timeline_segments")
    leaked_idx = NEW_INDEXES_0020 & indexes
    assert not leaked_idx, f"indexes should be removed by downgrade: {leaked_idx}"


def test_upgrade_preserves_existing_segment_default_values(
    baseline_engine: Engine,
) -> None:
    """已存在的 segment 行升级后：BGM/SFX 默认 NULL，ducking_db 默认 -12.0。"""
    # 在 baseline (0019，无 BGM/SFX 列) 上塞一条最小 segment 行。
    # 先建依赖：project + chapter + shot。
    with baseline_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, name, description, style, "
                "visual_style, seed, kind, unify_style, progress, stats, "
                "created_at, updated_at) VALUES "
                "('proj-1', 'Demo', '', '真人都市', '现实', 0, 'drama', "
                " 1, 0, '{}', "
                "'2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO chapters (id, project_id, \"index\", title, "
                "summary, raw_text, condensed_text, storyboard_count, status, "
                "created_at, updated_at) VALUES "
                "('chap-1', 'proj-1', 0, 'Chap 1', '', '', '', 0, 'draft', "
                "'2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO shots (id, chapter_id, \"index\", title, "
                "thumbnail, status, skip_extraction, script_excerpt, "
                "audio_strategy, created_at, updated_at) VALUES "
                "('shot-1', 'chap-1', 0, 'Shot 1', '', 'pending', 0, '', "
                " 'silent_with_tts', "
                "'2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO chapter_timeline_segments "
                "(id, chapter_id, shot_id, position, "
                "created_at, updated_at) VALUES "
                "('seg-1', 'chap-1', 'shot-1', 0, "
                "'2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )

    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    with baseline_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT bgm_file_id, sfx_file_id, bgm_ducking_db "
                "FROM chapter_timeline_segments WHERE id='seg-1'"
            )
        ).one()
    bgm_file_id, sfx_file_id, ducking_db = row
    assert bgm_file_id is None
    assert sfx_file_id is None
    assert ducking_db == pytest.approx(-12.0)


def test_orm_round_trip_bgm_sfx_ducking(baseline_engine: Engine) -> None:
    """ORM 写入 BGM/SFX file_id + 自定义 ducking_db，再读出应一致。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    from app.models.studio_prompts_files_timeline import FileItem
    from app.models.studio_projects import Chapter, Project
    from app.models.studio_shots import Shot
    from app.models.studio_timeline_chapter import ChapterTimelineSegment
    from app.models.types import (
        AudioStrategy,
        ChapterStatus,
        FileType,
        ProjectKind,
        ProjectStyle,
        ProjectVisualStyle,
        ShotStatus,
    )

    with Session(baseline_engine) as orm_session:
        proj = Project(
            id="proj-1",
            name="Demo",
            description="",
            style=ProjectStyle.real_people_city,
            visual_style=ProjectVisualStyle.live_action,
            seed=0,
            kind=ProjectKind.drama,
            unify_style=True,
            progress=0,
            stats={},
        )
        orm_session.add(proj)
        orm_session.flush()
        chap = Chapter(
            id="chap-1",
            project_id="proj-1",
            index=0,
            title="Chap 1",
            summary="",
            raw_text="",
            condensed_text="",
            storyboard_count=0,
            status=ChapterStatus.draft,
        )
        orm_session.add(chap)
        orm_session.flush()
        shot = Shot(
            id="shot-1",
            chapter_id="chap-1",
            index=0,
            title="Shot 1",
            thumbnail="",
            status=ShotStatus.pending,
            skip_extraction=False,
            script_excerpt="",
            audio_strategy=AudioStrategy.silent_with_tts,
        )
        orm_session.add(shot)
        bgm = FileItem(
            id="bgm-1",
            type=FileType.audio,
            name="bgm.mp3",
            storage_key="bgm/bgm.mp3",
        )
        sfx = FileItem(
            id="sfx-1",
            type=FileType.audio,
            name="sfx.mp3",
            storage_key="sfx/sfx.mp3",
        )
        orm_session.add_all([bgm, sfx])
        orm_session.flush()
        seg = ChapterTimelineSegment(
            id="seg-1",
            chapter_id="chap-1",
            shot_id="shot-1",
            position=0,
            bgm_file_id="bgm-1",
            sfx_file_id="sfx-1",
            bgm_ducking_db=-18.0,
        )
        orm_session.add(seg)
        orm_session.commit()

    with Session(baseline_engine) as orm_session:
        seg = orm_session.get(ChapterTimelineSegment, "seg-1")
        assert seg is not None
        assert seg.bgm_file_id == "bgm-1"
        assert seg.sfx_file_id == "sfx-1"
        assert seg.bgm_ducking_db == pytest.approx(-18.0)
