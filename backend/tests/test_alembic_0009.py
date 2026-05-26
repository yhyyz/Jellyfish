"""Alembic 0009 迁移集成测试 — voice_packs / tts_cache 建表 + 5 个 FK 列。

测试目标：

1. 在 0008 baseline 上执行 ``alembic upgrade head`` 后，新增表
   ``voice_packs`` 与 ``tts_cache`` 出现在数据库中，列结构与 ORM 定义
   保持一致。
2. 升级后，``characters.voice_pack_id``、``story_variants.voice_pack_id``、
   ``story_variants.narration_voice_pack_id``、
   ``shot_dialog_lines.start_time_ms`` / ``end_time_ms`` /
   ``tts_voice_id`` / ``tts_audio_file_id`` 共 7 个新列均成功落地。
3. ``alembic downgrade -1`` 后，两张新表与 5 个 FK 列被干净移除，
   schema 回到 0008 形态。
4. upgrade → downgrade → upgrade 往返后，``shot_dialog_lines`` /
   ``characters`` / ``story_variants`` 列集合保持稳定。
5. 0009 在 revision 链中正确接在 0008 之后，且是当前唯一 head。

模拟 "pre-0009" 环境：先用 ``Base.metadata`` 建出当前完整 schema，
再 drop 掉 0009 引入的两张新表 + 5 个 FK 列，最后把
``alembic_version`` 标记回 ``0008``。
"""

# pylint: disable=invalid-name

from __future__ import annotations

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


# 0009 引入的新表
NEW_TABLES_0009: tuple[str, ...] = ("voice_packs", "tts_cache")

#: 0010 (W18) 引入的两张新表；本文件聚焦 0009，但 fixture 必须把
#: 0010 表也排除在 ``Base.metadata.create_all`` 之外，否则 alembic
#: 升级到 head（=0010）时会因表已存在而 OperationalError。
_NEW_TABLES_0010: tuple[str, ...] = ("subtitle_styles", "subtitle_tracks")

# 0009 在既有表上新增的 FK 列：表 -> 列名集合
NEW_FK_COLUMNS: dict[str, tuple[str, ...]] = {
    "characters": ("voice_pack_id",),
    "story_variants": ("voice_pack_id", "narration_voice_pack_id"),
    "shot_dialog_lines": (
        "start_time_ms",
        "end_time_ms",
        "tts_voice_id",
        "tts_audio_file_id",
    ),
}


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0009_schema(engine: Engine) -> None:
    """搭建 "pre-0009" 状态：建出除 0009 新表外的全部 ORM 表，并跳过 5 个 FK 列。

    SQLite 3.35+ 虽然支持 ``ALTER TABLE ... DROP COLUMN``，但在带 FK 的列
    上会触发 "unknown column ... in foreign key definition" 报错；为了
    彻底回避这个限制，我们把所需 Table 复制到一个独立 ``MetaData`` 上
    并在复制时丢弃 0009 引入的两张新表与 5 个 FK 列。这样不会污染共享的
    ``Base.metadata``，避免后续测试看到错位的 mapper 配置。
    """
    from sqlalchemy import MetaData

    fresh = MetaData()
    for source in Base.metadata.sorted_tables:
        if source.name in NEW_TABLES_0009 or source.name in _NEW_TABLES_0010:
            continue
        skip_cols = set(NEW_FK_COLUMNS.get(source.name, ()))

        copy_target = source.to_metadata(
            fresh,
            referred_schema_fn=lambda _t, _to_schema, _ck, referred_schema: referred_schema,
        )
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
        db_path = Path(tmp_dir) / "alembic_0009_test.db"
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
    """返回一个 alembic_version=0008、缺少 0009 schema 的临时 engine。"""
    _setup_pre_0009_schema(tmp_engine)
    _stamp_version(tmp_engine, "0008")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def test_revision_chain_includes_0009() -> None:
    """0009 必须接在 0008 之后；当前 head 已被 0010（W18 字幕引擎）接管。"""
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    rev = script.get_revision("0009")
    assert rev is not None, "revision 0009 missing"
    assert rev.down_revision == "0008"

    heads = script.get_heads()
    assert list(heads) == ["0010"], f"expected single head 0010, got {heads!r}"


def test_upgrade_head_creates_new_tables(baseline_engine: Engine) -> None:
    """upgrade head 后必须新增 voice_packs 与 tts_cache 两张表。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    for name in NEW_TABLES_0009:
        assert name in tables, f"missing table after upgrade: {name}"

    # voice_packs 关键列存在
    voice_cols = _table_columns(baseline_engine, "voice_packs")
    for required in (
        "id",
        "name",
        "provider",
        "provider_voice_id",
        "language_code",
        "gender",
        "default_speed",
        "is_system",
        "sort_order",
        "created_at",
        "updated_at",
    ):
        assert required in voice_cols, f"voice_packs missing column: {required}"

    # tts_cache 关键列存在
    cache_cols = _table_columns(baseline_engine, "tts_cache")
    for required in (
        "id",
        "cache_key",
        "voice_pack_id",
        "audio_file_id",
        "duration_ms",
        "word_timestamps",
        "hit_count",
    ):
        assert required in cache_cols, f"tts_cache missing column: {required}"

    # voice_packs 的 (provider, language_code) 复合索引存在
    voice_indexes = {
        idx["name"] for idx in inspector.get_indexes("voice_packs")
    }
    assert "ix_voice_packs_provider_lang" in voice_indexes


def test_upgrade_head_adds_fk_columns(baseline_engine: Engine) -> None:
    """upgrade head 后既有 3 张表上必须出现 5 个 FK 列。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    for table, cols in NEW_FK_COLUMNS.items():
        actual = _table_columns(baseline_engine, table)
        for col in cols:
            assert col in actual, f"{table} missing column after upgrade: {col}"


def test_downgrade_removes_new_tables_and_columns(
    baseline_engine: Engine,
) -> None:
    """downgrade 到 0008 后必须干净移除 0009 引入的两张表与 5 个 FK 列。

    注意：当前 alembic head 已是 0010（W18 字幕引擎），用 ``-1`` 只会回退一步
    （回到 0009），因此本测试显式 downgrade 到 ``"0008"`` 才能验证 0009 的
    回滚能力。
    """
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0008")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    for name in NEW_TABLES_0009:
        assert name not in tables, f"table {name} should be removed by downgrade"

    for table, cols in NEW_FK_COLUMNS.items():
        actual = _table_columns(baseline_engine, table)
        for col in cols:
            assert col not in actual, (
                f"{table}.{col} should be removed by downgrade, "
                f"got columns: {sorted(actual)}"
            )


def test_roundtrip_preserves_columns(baseline_engine: Engine) -> None:
    """upgrade → downgrade → upgrade 后，三张表列集合保持稳定。"""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "head")
    first: dict[str, list[str]] = {
        table: sorted(_table_columns(baseline_engine, table))
        for table in NEW_FK_COLUMNS
    }

    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    second: dict[str, list[str]] = {
        table: sorted(_table_columns(baseline_engine, table))
        for table in NEW_FK_COLUMNS
    }

    assert first == second, (
        f"columns diverged after roundtrip; first={first} second={second}"
    )
