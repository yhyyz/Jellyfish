"""Alembic 0008 迁移集成测试 — shots 表新增两个 P3 R2V 配套列。

测试目标：

1. 在 0007 baseline 上执行 ``alembic upgrade head`` 后，``shots`` 表中
   新增 ``audio_strategy`` 与 ``product_focus_level`` 两列；列类型、
   非空约束、server_default 与 0008 迁移声明一致。
2. ``alembic downgrade -1`` 后，两列被移除，``shots`` 表回到 0007 形态。
3. upgrade → downgrade → upgrade 往返后，``shots`` 列集合保持稳定，
   保证迁移真正幂等。
4. 0008 在 revision 链中正确接在 0007 之后，且是当前唯一 head。
5. 升级前已存在的 ``shots`` 行能拿到 ``silent_with_tts`` / ``none``
   的 server_default 默认值，避免新列引入造成 NOT NULL 违约。

为了模拟 "pre-0008" 环境（``shots`` 表无 audio_strategy/product_focus_level），
fixture 先用 ``Base.metadata`` 建出当前完整 schema，再显式 drop 这两列与
``alembic_version`` 上的 0008 标记，把版本号回退到 0007。
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


NEW_COLUMNS: tuple[str, ...] = ("audio_strategy", "product_focus_level")


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径，避免依赖测试启动 cwd。"""
    return Path(__file__).resolve().parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。

    项目 ``alembic/env.py`` 通过 ``app.config.settings.database_url`` 解析
    连接 URL 并覆盖 CLI 传入值，因此 fixture 还必须 monkeypatch
    ``settings.database_url``，由 ``baseline_engine`` 负责。
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0008_schema(engine: Engine) -> None:
    """搭建 "pre-0008" 状态：完整 schema 但 ``shots`` 表无新列。

    ``Base.metadata.create_all`` 同样会物化 0009 引入的两张新表
    （voice_packs / tts_cache）与 5 个 FK 列；为了让后续 0008 upgrade
    在 0007 baseline 上执行而不撞库，我们把 ORM 表复制到独立 MetaData
    上，并在复制时丢弃 0009 的新表与新列。这样不会污染共享的全局
    ``Base.metadata`` mapper 配置。
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
    new_tables_0009 = ("voice_packs", "tts_cache")

    fresh = MetaData()
    for source in Base.metadata.sorted_tables:
        if source.name in new_tables_0009:
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
        # SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN，可直接回退到 0007 形态。
        for col in NEW_COLUMNS:
            conn.execute(text(f"ALTER TABLE shots DROP COLUMN {col}"))


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
    """提供一个临时文件 SQLite engine；alembic.command 内部会复用同一文件。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "alembic_0008_test.db"
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
    """返回一个 alembic_version=0007、shots 无新列的临时 engine。"""
    _setup_pre_0008_schema(tmp_engine)
    _stamp_version(tmp_engine, "0007")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


def _shot_columns(engine: Engine) -> dict[str, dict[str, object]]:
    """返回 ``shots`` 表所有列的 (name -> info) 映射，方便断言。"""
    inspector = inspect(engine)
    return {col["name"]: col for col in inspector.get_columns("shots")}


def test_revision_chain_includes_0008() -> None:
    """0008 必须接在 0007 之后；当前 head 已被 0009 接管。"""
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    rev = script.get_revision("0008")
    assert rev is not None, "revision 0008 missing"
    assert rev.down_revision == "0007"

    heads = script.get_heads()
    assert list(heads) == ["0009"], f"expected single head 0009, got {heads!r}"


def test_upgrade_head_adds_new_columns(baseline_engine: Engine) -> None:
    """升级到 0008 后 shots 表必须带有两个新列且 NOT NULL + server_default。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0008")

    cols = _shot_columns(baseline_engine)
    for name in NEW_COLUMNS:
        assert name in cols, f"missing column after upgrade: {name}"
        info = cols[name]
        assert info["nullable"] is False, f"{name} should be NOT NULL"
        # SQLAlchemy inspector 暴露 server_default 字段；SQLite 上为字面量字符串。
        default = info.get("default")
        assert default is not None, f"{name} should have server_default"

    # 默认值与 0008 声明一致；SQLite 把字符串字面量保留为带引号形式。
    audio_default = cols["audio_strategy"].get("default") or ""
    focus_default = cols["product_focus_level"].get("default") or ""
    assert "silent_with_tts" in str(audio_default)
    assert "none" in str(focus_default)


def test_downgrade_removes_new_columns(baseline_engine: Engine) -> None:
    """downgrade -1 后 shots 表回到 0007 形态，两列被干净移除。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0008")
    command.downgrade(cfg, "0007")

    cols = _shot_columns(baseline_engine)
    for name in NEW_COLUMNS:
        assert name not in cols, f"column {name} should be removed by downgrade"


def test_roundtrip_preserves_shots_columns(baseline_engine: Engine) -> None:
    """upgrade → downgrade → upgrade 后 shots 列集合保持稳定。"""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "0008")
    first = sorted(_shot_columns(baseline_engine).keys())

    command.downgrade(cfg, "0007")
    command.upgrade(cfg, "0008")
    second = sorted(_shot_columns(baseline_engine).keys())

    assert first == second, (
        f"shots column set diverged after roundtrip: first={first}, second={second}"
    )


def test_existing_row_backfilled_on_upgrade(baseline_engine: Engine) -> None:
    """0008 之前已存在的 shots 行升级后应拿到 server_default 值，避免 NOT NULL 违约。"""
    shot_id = "shot-pre-0008"
    chapter_id = "chap-pre-0008"
    project_id = "proj-pre-0008"

    with baseline_engine.begin() as conn:
        # 插入最小可行 project / chapter / shot 链路；只填必填列。
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, name, description, style, visual_style, kind, seed, "
                " unify_style, progress, stats) "
                "VALUES (:id, :name, '', '真人都市', '现实', 'drama', 0, 1, 0, '{}')"
            ),
            {"id": project_id, "name": "pre-0008-project"},
        )
        conn.execute(
            text(
                'INSERT INTO chapters '
                '(id, project_id, title, summary, "index", status, '
                ' raw_text, condensed_text, storyboard_count) '
                "VALUES (:id, :pid, :title, '', 0, 'draft', '', '', 0)"
            ),
            {"id": chapter_id, "pid": project_id, "title": "pre-0008-chapter"},
        )
        conn.execute(
            text(
                'INSERT INTO shots '
                '(id, chapter_id, "index", title, thumbnail, status, '
                ' skip_extraction, script_excerpt) '
                "VALUES (:id, :cid, 0, :title, '', 'pending', 0, '')"
            ),
            {"id": shot_id, "cid": chapter_id, "title": "pre-0008-shot"},
        )

    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0008")

    with baseline_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT audio_strategy, product_focus_level "
                "FROM shots WHERE id = :id"
            ),
            {"id": shot_id},
        ).one()
    assert row.audio_strategy == "silent_with_tts"
    assert row.product_focus_level == "none"
