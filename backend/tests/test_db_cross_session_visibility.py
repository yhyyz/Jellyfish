"""W19b-T1: SQLite WAL 跨 session 可见性回归测试。

为什么存在
----------

修复前的 bug：

1. aiosqlite 底层依赖 stdlib ``sqlite3``，默认是 "legacy transaction mode"
   —— ``SELECT`` 不会自动 ``BEGIN``，仅写语句才会隐式开事务。
2. 叠加 WAL 模式后，池化连接会持有上次 SELECT 时的 WAL read-snapshot
   终止位（end mark）；如果新 session 复用了这条连接，又没有发 BEGIN，
   就会继续复用旧 snapshot。
3. 表现：HTTP 请求 A 创建并提交行 X，HTTP 请求 B 立刻 SELECT X，
   返回 None。加 1.5s ``time.sleep`` 就能掩盖。

修复后必须满足
--------------

- session A 提交后立即关闭。
- 新开 session B（可能复用上一条池化连接）``get(Model, id)``。
- **不加任何 sleep**，必须能拿到行。

本文件构造一份针对 ``app.core.db._build_engine()`` 的临时 SQLite
WAL 文件，复用生产代码的事件监听器注册路径，验证：

* 单次：1 次 提交→新 session 读 必须立刻可见。
* 50 次背靠背：循环 50 轮，全部命中，杜绝偶发幻读。
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.config import settings
from app.core import db as db_module
from app.core.db import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _import_all_models() -> None:
    """触发所有 ORM 模型导入，使其挂到 ``Base.metadata`` 上。"""
    # pylint: disable=import-outside-toplevel,unused-import
    import app.models.llm  # noqa: F401
    import app.models.studio  # noqa: F401
    import app.models.task  # noqa: F401
    import app.models.task_links  # noqa: F401


@pytest.fixture
def tmp_db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """把 ``settings.database_url`` 临时切到本测试独占的 SQLite 文件。

    通过 monkeypatch settings 让 ``_build_engine()`` 沿用生产路径
    （包含 SQLite 分支 + connect/begin 监听器），从而真正测到修复点。
    """
    db_file = tmp_path / "b1_visibility.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setattr(settings, "database_url", url)
    yield url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_kwargs(idx: int) -> dict[str, object]:
    """构造一条最小可写入的 Provider 行参数。

    Provider 是 schema 里必填字段最少的模型之一（只需 id / name / base_url），
    用作回归测试载体可以避免拉进无关业务约束。
    """
    return {
        "id": f"prov-b1-{idx}",
        "name": f"prov-b1-{idx}",
        "base_url": "https://example.invalid",
    }


async def _bootstrap_engine() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """走生产 ``_build_engine()`` 通路构建引擎并建表。

    返回值：(engine, sessionmaker)。调用方负责最终 ``await engine.dispose()``。
    """
    _import_all_models()
    # pylint: disable=protected-access
    engine: AsyncEngine = db_module._build_engine()
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 验证 WAL 监听器确实生效；否则后续断言意义会被掩盖。
    async with engine.connect() as conn:
        mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        assert mode == "wal", f"Expected WAL mode after connect listener, got {mode!r}"

    return engine, maker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_committed_row_visible_to_fresh_session_immediately(
    tmp_db_url: str,  # noqa: ARG001  # 通过 monkeypatch 间接生效
) -> None:
    """单次：A 提交→关闭→新 session B ``get`` 必须立刻可见（无 sleep）。"""
    engine, maker = await _bootstrap_engine()
    try:
        from app.models.llm import Provider  # pylint: disable=import-outside-toplevel

        async with maker() as session_a:
            session_a.add(Provider(**_provider_kwargs(0)))
            await session_a.commit()

        async with maker() as session_b:
            row = await session_b.get(Provider, "prov-b1-0")

        assert row is not None, (
            "Cross-session visibility regression: fresh session could not see the just-"
            "committed row without sleeping. Verify B1 fix in app/core/db.py is intact."
        )
        assert row.id == "prov-b1-0"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_50x_back_to_back_create_fetch_no_phantom(
    tmp_db_url: str,  # noqa: ARG001
) -> None:
    """50 轮背靠背：每轮 insert→commit→关闭→新 session fetch，全部必须可见。

    50 次足以反复打到连接池中那条 "持有旧 read-snapshot" 的连接，
    用统计意义压住偶发幻读。
    """
    engine, maker = await _bootstrap_engine()
    try:
        from app.models.llm import Provider  # pylint: disable=import-outside-toplevel

        for i in range(1, 51):
            async with maker() as session_a:
                session_a.add(Provider(**_provider_kwargs(i)))
                await session_a.commit()

            async with maker() as session_b:
                row = await session_b.get(Provider, f"prov-b1-{i}")

            assert row is not None, (
                f"Iteration {i}: fresh session could not see the row committed in the "
                "previous session. WAL stale-snapshot bug has reappeared."
            )
            # 防止异步 GC 把 session_b 对应的连接释放慢，主动让出一次调度，
            # 让池化连接更快回到空闲队列；这样下一轮就更可能复用同一条连接，
            # 提升对池化复用路径的覆盖。
            await asyncio.sleep(0)
    finally:
        await engine.dispose()
