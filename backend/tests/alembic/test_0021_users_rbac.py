"""Alembic 0021 迁移集成测试 — users 表建表 + 索引 + downgrade 回退。

W32-T1 引入 RBAC 第一张表 ``users``。本测试覆盖：

1. ``users`` 表在 upgrade 后存在，列结构与 ORM 一致；
2. ``username`` / ``email`` 唯一索引生效；
3. ``role`` / ``is_active`` 普通索引存在；
4. 0021 在 revision 链中接在 0020 之后；
5. upgrade → downgrade → upgrade 往返后列集合稳定；
6. UserRole enum 序列化为 'admin' / 'member' / 'viewer'。

构造 "pre-0021" 状态：用 ``Base.metadata`` 建出当前完整 schema，
单独 drop ``users`` 表，最后把 ``alembic_version`` 标记回 ``0020``。
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

import app.models  # noqa: F401  pylint: disable=unused-import
import app.models.user  # noqa: F401  pylint: disable=unused-import
from app.models.types import UserRole


NEW_TABLE = "users"


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0021_schema(engine: Engine) -> None:
    """搭建 pre-0021 状态：建出全部 ORM 表但跳过 ``users``。

    复制需要的表到一个独立 ``MetaData``，剔除 ``users`` 后 create_all。
    这样不会污染共享 ``Base.metadata``，避免后续测试看到错位的 mapper 配置。
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
        db_path = Path(tmp_dir) / "alembic_0021_test.db"
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
    """返回一个 alembic_version=0020、缺少 users 表的临时 engine。"""
    _setup_pre_0021_schema(tmp_engine)
    _stamp_version(tmp_engine, "0020")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    with tmp_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


def test_revision_chain_includes_0021() -> None:
    """0021 必须接在 0020 之后；不强行约束当前 head（race-aware）。"""
    cfg = _make_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)

    rev = script.get_revision("0021")
    assert rev is not None, "revision 0021 missing"
    assert rev.down_revision == "0020", (
        f"expected 0021.down_revision=0020, got {rev.down_revision!r}"
    )


def test_upgrade_creates_users_table(baseline_engine: Engine) -> None:
    """upgrade 0021 后必须新增 users 表，且关键列齐全。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0021")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE in tables, f"missing table after upgrade: {NEW_TABLE}"

    cols = _table_columns(baseline_engine, NEW_TABLE)
    for required in (
        "id",
        "username",
        "email",
        "hashed_password",
        "role",
        "is_active",
        "created_at",
        "updated_at",
    ):
        assert required in cols, f"{NEW_TABLE} missing column: {required}"


def test_upgrade_creates_unique_indexes(baseline_engine: Engine) -> None:
    """username / email 唯一索引生效；role / is_active 普通索引存在。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0021")

    with baseline_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name='users' "
                "ORDER BY name"
            )
        ).all()
    by_name = {row[0]: row[1] or "" for row in rows}

    assert "ix_users_username" in by_name, (
        f"missing ix_users_username; available: {sorted(by_name)}"
    )
    assert "UNIQUE" in by_name["ix_users_username"].upper()

    assert "ix_users_email" in by_name
    assert "UNIQUE" in by_name["ix_users_email"].upper()

    assert "ix_users_role" in by_name
    assert "UNIQUE" not in by_name["ix_users_role"].upper()

    assert "ix_users_is_active" in by_name
    assert "UNIQUE" not in by_name["ix_users_is_active"].upper()


def test_unique_username_prevents_duplicate(baseline_engine: Engine) -> None:
    """同一 username 不能插入两份用户行（UNIQUE INDEX 生效）。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0021")

    with baseline_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, "
                "role, is_active) VALUES "
                "('uid-1', 'alice', 'a@example.com', 'h1', 'member', 1)"
            )
        )

    import sqlite3

    with pytest.raises((sqlite3.IntegrityError, Exception)) as exc_info:
        with baseline_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password, "
                    "role, is_active) VALUES "
                    "('uid-2', 'alice', 'a2@example.com', 'h2', 'member', 1)"
                )
            )
    err_msg = str(exc_info.value).lower()
    assert "unique" in err_msg or "constraint" in err_msg, (
        f"expected UNIQUE error on username, got: {exc_info.value!r}"
    )


def test_downgrade_removes_users_table(baseline_engine: Engine) -> None:
    """downgrade 0020 后 users 表被干净移除。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "0021")
    command.downgrade(cfg, "0020")

    inspector = inspect(baseline_engine)
    tables = set(inspector.get_table_names())
    assert NEW_TABLE not in tables, (
        f"{NEW_TABLE} should be removed by downgrade"
    )


def test_roundtrip_preserves_columns(baseline_engine: Engine) -> None:
    """upgrade → downgrade → upgrade 后，users 列集合保持稳定。"""
    cfg = _make_alembic_config(str(baseline_engine.url))

    command.upgrade(cfg, "0021")
    first = sorted(_table_columns(baseline_engine, NEW_TABLE))

    command.downgrade(cfg, "0020")
    command.upgrade(cfg, "0021")
    second = sorted(_table_columns(baseline_engine, NEW_TABLE))

    assert first == second, (
        f"列在 roundtrip 后变化：first={first!r} second={second!r}"
    )


def test_user_role_enum_string_values() -> None:
    """UserRole 枚举值序列化为 'admin' / 'member' / 'viewer' 字符串。"""
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.MEMBER.value == "member"
    assert UserRole.VIEWER.value == "viewer"
    assert str(UserRole.ADMIN.value) == "admin"
    assert UserRole("admin") is UserRole.ADMIN
    assert UserRole("member") is UserRole.MEMBER
    assert UserRole("viewer") is UserRole.VIEWER
