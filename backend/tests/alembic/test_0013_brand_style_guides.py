"""Alembic 0013 迁移集成测试 — brand_style_guides 建表 + 1:1 / CASCADE 校验。

测试目标（≥3 用例）：

1. ``brand_style_guides`` 表在 upgrade 后存在，列结构 / 唯一约束 / 外键
   均与 ORM 定义一致；
2. ``product_id`` 外键带 ``ON DELETE CASCADE``：删除 products 行时
   brand_style_guides 行同步消失（行为级断言）；
3. 同一 ``product_id`` 不能插入两份规范（``UniqueConstraint`` 生效）。
4. 0013 在 revision 链中正确接在 ``0012`` 之后（race-aware：与 sibling
   任务 0014 并行时仍保留唯一线性接续）。
5. upgrade → downgrade → upgrade 往返后，列集合稳定。

构造 "pre-0013" 状态：用 ``Base.metadata`` 建出当前完整 schema，再
单独 drop ``brand_style_guides`` 表，最后把 ``alembic_version`` 标记
回 ``0012``，避免重复建表。
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
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.core.db import Base

# 触发所有 ORM 模块导入，让 Base.metadata 拥有完整定义。
import app.models  # noqa: F401  pylint: disable=unused-import
import app.models.brand_style_guide  # noqa: F401  pylint: disable=unused-import


NEW_TABLE = "brand_style_guides"


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0013_schema(engine: Engine) -> None:
    """搭建 pre-0013 状态：建出全部 ORM 表但跳过 ``brand_style_guides``。

    复制需要的表到一个独立 ``MetaData``，剔除 ``brand_style_guides`` 后
    create_all。这样不会污染共享 ``Base.metadata``，避免后续测试看到
    错位的 mapper 配置。
    """
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
        db_path = Path(tmp_dir) / "alembic_0013_test.db"
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
    """返回一个 alembic_version=0012、缺少 brand_style_guides 的 engine。"""
    _setup_pre_0013_schema(tmp_engine)
    _stamp_version(tmp_engine, "0012")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    # 启用 SQLite FK 强制，否则 CASCADE 测试无法生效。
    with tmp_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def test_revision_chain_includes_0013() -> None:
    """0013 必须接在 0012 之后；不强行约束当前 head（race-aware：sibling
    任务可能产生 0014/0015 head，集成阶段统一 rebase）。"""
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    rev = script.get_revision("0013")
    assert rev is not None, "revision 0013 missing"
    assert rev.down_revision == "0012", (
        f"expected 0013.down_revision=0012, got {rev.down_revision!r}"
    )


def test_upgrade_creates_brand_style_guides_table(
    baseline_engine: Engine,
) -> None:
    """upgrade 0013 后必须新增 brand_style_guides 表，且关键列齐全。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0013")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE in tables, f"missing table after upgrade: {NEW_TABLE}"

    cols = _table_columns(baseline_engine, NEW_TABLE)
    for required in (
        "id",
        "product_id",
        "forced_phrases",
        "banned_patterns",
        "required_endings",
        "brand_persona_tagline",
        "created_at",
        "updated_at",
    ):
        assert required in cols, f"{NEW_TABLE} missing column: {required}"

    # 唯一约束：product_id 唯一
    uniques = {
        tuple(uc["column_names"])
        for uc in inspector.get_unique_constraints(NEW_TABLE)
    }
    assert ("product_id",) in uniques, (
        f"{NEW_TABLE} missing UNIQUE(product_id) constraint, got {uniques!r}"
    )

    # 外键：product_id → products.id
    fks = inspector.get_foreign_keys(NEW_TABLE)
    fk_targets = {fk["referred_table"] for fk in fks}
    assert "products" in fk_targets, (
        f"{NEW_TABLE} missing FK to products, got {fks!r}"
    )


def test_cascade_deletes_brand_style_guide_with_product(
    baseline_engine: Engine,
) -> None:
    """删除 products 行时 brand_style_guides 行同步消失（FK CASCADE）。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0013")

    with baseline_engine.begin() as conn:
        # 启用 FK 强制（每连接独立设置）
        conn.execute(text("PRAGMA foreign_keys = ON"))
        # 准备一条 product
        conn.execute(
            text(
                "INSERT INTO products (id, name, brand, category, "
                "description, selling_points, pain_points_solved, "
                "target_audience, catchphrases, competitor_names, "
                "health_disclaimer_required, visual_style, style) "
                "VALUES (:id, :name, '', 'other', '', '[]', '[]', '{}', "
                "'[]', '[]', 0, '现实', '真人都市')"
            ),
            {"id": "p_cascade", "name": "cascade-product"},
        )
        # 挂一条规范
        conn.execute(
            text(
                "INSERT INTO brand_style_guides (id, product_id, "
                "forced_phrases, banned_patterns, required_endings, "
                "brand_persona_tagline) "
                "VALUES (:id, :pid, '[]', '[]', '[]', '')"
            ),
            {"id": "g1", "pid": "p_cascade"},
        )

    # 删除 product
    with baseline_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(
            text("DELETE FROM products WHERE id = :id"),
            {"id": "p_cascade"},
        )

    # 规范应被 CASCADE 删除
    with baseline_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM brand_style_guides "
                "WHERE product_id = :pid"
            ),
            {"pid": "p_cascade"},
        ).scalar_one()
    assert result == 0, (
        "brand_style_guides 行未被 CASCADE 删除"
    )


def test_unique_constraint_prevents_duplicate_per_product(
    baseline_engine: Engine,
) -> None:
    """同一 product 下不能插入两份品牌话术规范。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0013")

    with baseline_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(
            text(
                "INSERT INTO products (id, name, brand, category, "
                "description, selling_points, pain_points_solved, "
                "target_audience, catchphrases, competitor_names, "
                "health_disclaimer_required, visual_style, style) "
                "VALUES (:id, :name, '', 'other', '', '[]', '[]', '{}', "
                "'[]', '[]', 0, '现实', '真人都市')"
            ),
            {"id": "p_unique", "name": "unique-product"},
        )
        conn.execute(
            text(
                "INSERT INTO brand_style_guides (id, product_id, "
                "forced_phrases, banned_patterns, required_endings, "
                "brand_persona_tagline) "
                "VALUES (:id, :pid, '[]', '[]', '[]', '')"
            ),
            {"id": "g1", "pid": "p_unique"},
        )

    # 第二次插入应当报错（UNIQUE 约束）
    import sqlite3

    with pytest.raises((sqlite3.IntegrityError, Exception)) as exc_info:
        with baseline_engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(
                text(
                    "INSERT INTO brand_style_guides (id, product_id, "
                    "forced_phrases, banned_patterns, required_endings, "
                    "brand_persona_tagline) "
                    "VALUES (:id, :pid, '[]', '[]', '[]', '')"
                ),
                {"id": "g2", "pid": "p_unique"},
            )
    err_msg = str(exc_info.value).lower()
    assert "unique" in err_msg or "constraint" in err_msg, (
        f"expected UNIQUE constraint error, got: {exc_info.value!r}"
    )


def test_downgrade_removes_brand_style_guides(
    baseline_engine: Engine,
) -> None:
    """downgrade 0012 后 brand_style_guides 表被干净移除。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0013")
    command.downgrade(cfg, "0012")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE not in tables, (
        f"{NEW_TABLE} should be removed by downgrade"
    )


def test_roundtrip_preserves_columns(baseline_engine: Engine) -> None:
    """upgrade → downgrade → upgrade 后，brand_style_guides 列集合保持稳定。"""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "0013")
    first = sorted(_table_columns(baseline_engine, NEW_TABLE))

    command.downgrade(cfg, "0012")
    command.upgrade(cfg, "0013")
    second = sorted(_table_columns(baseline_engine, NEW_TABLE))

    assert first == second, (
        f"列在 roundtrip 后变化：first={first!r} second={second!r}"
    )
