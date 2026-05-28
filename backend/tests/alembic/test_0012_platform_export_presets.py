"""Alembic 0012 迁移集成测试 — platform_export_presets 建表（W23-T1，P4 Wave A）。

测试目标：

1. 0012 在 revision 链中正确接在 0011 之后；script 能解析。
2. 在 0011 baseline 上执行 ``alembic upgrade 0012`` 后，新增表
   ``platform_export_presets`` 出现在数据库中；列结构、3 个 FK 列、
   主索引齐全。
3. ``alembic downgrade -1`` 后，新表被干净移除，schema 回到 0011 形态。
4. upgrade → downgrade → upgrade 往返后，``platform_export_presets``
   列集合保持稳定（迁移真正幂等）。

为了模拟 "pre-0012" 环境（数据库无 platform_export_presets 表），
fixture 先用 ``Base.metadata`` 建出当前完整 schema，再 drop 0012 引入
的新表，最后把 ``alembic_version`` 标记回 ``0011``。

注意：当前仓库存在 0012 / 0013 / 0014 三条 sister branch（均 down_revision=
0011），三者构成 alembic multi-head 状态。本测试只关心 0012 自身的
upgrade/downgrade，全部用显式 revision id 驱动 alembic 命令，避免命中
multi-head 时 ``head`` 别名的歧义。
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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.core.db import Base

import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.platform_export_preset  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.subtitle  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import


NEW_TABLE = "platform_export_presets"


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0012_schema(engine: Engine) -> None:
    """搭建 "pre-0012" 状态：建出除 0012 新表外的全部 ORM 表。

    与 0009 / 0010 / 0011 测试一致，复制 ``Base.metadata`` 到独立
    ``MetaData``，跳过 0012 引入的新表，避免 ALTER 后悬挂 FK。
    """
    from sqlalchemy import MetaData

    fresh = MetaData()
    for source in Base.metadata.sorted_tables:
        if source.name == NEW_TABLE:
            continue
        source.to_metadata(
            fresh,
            referred_schema_fn=lambda _t, _to_schema, _ck, referred_schema: referred_schema,
        )

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
        db_path = Path(tmp_dir) / "alembic_0012_test.db"
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
    """返回一个 alembic_version=0011、缺少 0012 schema 的临时 engine。"""
    _setup_pre_0012_schema(tmp_engine)
    _stamp_version(tmp_engine, "0011")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def test_revision_chain_includes_0012() -> None:
    """0012 必须接在 0011 之后；script 能解析到这个 revision。"""
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    rev = script.get_revision("0012")
    assert rev is not None, "revision 0012 missing"
    assert rev.down_revision == "0011"


def test_upgrade_to_0012_creates_new_table(baseline_engine: Engine) -> None:
    """upgrade 0012 后必须新增 platform_export_presets 表。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0012")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE in tables, f"missing table after upgrade: {NEW_TABLE}"

    cols = _table_columns(baseline_engine, NEW_TABLE)
    expected = {
        "id",
        "name",
        "platform",
        "aspect_ratio",
        "max_duration_sec",
        "subtitle_style_id",
        "voice_pack_id",
        "watermark_file_id",
        "sticker_specs",
        "file_format",
        "codec_preset",
        "loudness_lufs",
        "is_system",
        "sort_order",
        "description",
        "created_at",
        "updated_at",
    }
    missing = expected - cols
    assert not missing, f"platform_export_presets missing columns: {missing}"

    indexes = {idx["name"] for idx in inspector.get_indexes(NEW_TABLE)}
    assert "ix_platform_export_presets_platform_aspect" in indexes
    assert "ix_platform_export_presets_platform" in indexes
    assert "ix_platform_export_presets_subtitle_style_id" in indexes
    assert "ix_platform_export_presets_voice_pack_id" in indexes
    assert "ix_platform_export_presets_watermark_file_id" in indexes


def test_downgrade_removes_new_table(baseline_engine: Engine) -> None:
    """downgrade 0011 后必须干净移除 0012 引入的 platform_export_presets 表。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0012")
    command.downgrade(cfg, "0011")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE not in tables, (
        f"table {NEW_TABLE} should be removed by downgrade"
    )


def test_roundtrip_preserves_columns(baseline_engine: Engine) -> None:
    """upgrade → downgrade → upgrade 后，platform_export_presets 列集合保持稳定。"""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "0012")
    first = sorted(_table_columns(baseline_engine, NEW_TABLE))

    command.downgrade(cfg, "0011")
    command.upgrade(cfg, "0012")
    second = sorted(_table_columns(baseline_engine, NEW_TABLE))

    assert first == second, (
        f"columns diverged after roundtrip; first={first} second={second}"
    )
