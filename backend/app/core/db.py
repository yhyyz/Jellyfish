"""SQLAlchemy 异步引擎与会话。"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _is_sqlite(url: str) -> bool:
    """判断 DATABASE_URL 是否指向 SQLite（含 aiosqlite 驱动）。

    用途：仅在 SQLite 路径上启用 PRAGMA / 显式 BEGIN 等专属修复，
    避免污染 MySQL / PostgreSQL 等远端引擎的连接行为。
    """
    return url.startswith("sqlite+aiosqlite://") or url.startswith("sqlite://")


def _build_engine() -> AsyncEngine:
    """构建异步数据库引擎；针对 SQLite 修复跨 session 可见性问题。

    做什么：
    - 非 SQLite（MySQL / PostgreSQL）保持原有连接池策略，仅做最小变更。
    - SQLite 走专属分支，开启 WAL + 外键 + 显式事务边界。

    为什么 SQLite 必须特殊处理：
    aiosqlite 底层用的是 stdlib 的 ``sqlite3`` 驱动，默认处于 "legacy
    transaction mode"：``SELECT`` 不会自动触发 ``BEGIN``；只有写语句
    才会隐式开启事务。

    叠加 WAL 模式后会出现严重 bug：
    - 池化的连接会持有上次 SELECT 时建立的 read-snapshot 终止位（end mark）。
    - 另一会话 INSERT + COMMIT 之后立即拿到这条连接做 SELECT，
      由于连接没有重新 ``BEGIN``，仍然复用旧 snapshot，
      读到的是 producer 提交之前的世界 —— 表现为 "刚创建的行查不到"。

    解决方案（必须三条同时满足）：
    1. ``connect_args={"isolation_level": None}``
       —— 关闭 sqlite3 的自动事务管理，把事务边界交还给 SQLAlchemy。
    2. ``connect`` 事件监听：连接首次建立时立刻把核心 PRAGMA 写死。
       其中 ``journal_mode=WAL`` 是项目刻意的选择（多 reader + 单 writer）。
    3. ``begin`` 事件监听：在 SA 准备开新事务时**显式**发 ``BEGIN``。
       注意 —— 一旦设置 ``isolation_level=None``，SA 会停止自己发 BEGIN，
       如果不补这一步，事务边界会静默失效（看起来像 "永远在 autocommit"），
       新 session 仍然复用旧 snapshot，bug 依旧。

    部署提示：
    监听器必须注册在 ``_build_engine()`` 内部，因为 ``reset_db_runtime()``
    在 Celery prefork 子进程会重建引擎；如果监听器写在模块顶层，
    重建后的新引擎就会丢掉这些 hook，bug 会在 worker 进程内复活。
    """
    kwargs: dict[str, Any] = {
        "echo": settings.debug,
        "future": True,
    }

    if _is_sqlite(settings.database_url):
        # SQLite 不需要也不支持 MySQL 那套连接池参数；最关键的是
        # 把事务控制权从 sqlite3 驱动收回到 SQLAlchemy。
        # ``timeout`` 参数会直接传到 ``sqlite3.connect(timeout=...)`` ——
        # 在 C 层立即调用 sqlite3_busy_timeout(60000)，比 PRAGMA listener
        # 更可靠（不依赖 cursor 路由 / 后台线程时序），是消除
        # SQLITE_BUSY 21ms 瞬间失败的根因修复。
        kwargs["connect_args"] = {"isolation_level": None, "timeout": 60.0}
    else:
        # 远端数据库（MySQL / PostgreSQL）：用 NullPool 消除连接复用导致的
        # 跨请求 visibility race。
        #
        # T2c：T2a/T2b 同时设了 engine-level isolation_level=READ COMMITTED 与
        # connect_args.init_command，独立验证 fresh engine 下 3/3 connection
        # 为 READ-COMMITTED；但实测 uvicorn 长跑后，复用 pool 中的连接做
        # `db.get(ShotDetail, id)` 仍然查不到 2ms 前另一连接 COMMIT 的记录，
        # 表现为持久 (>1s 仍查不到) 的 REPEATABLE READ 快照行为。
        # 一旦换 NullPool（每次 checkout 都重连，连接握手即跑 init_command，
        # 用完即关），race 立即消失。
        #
        # NullPool 的代价：每个 HTTP 请求都重连 MySQL，本地开发量级完全可承受
        # （实际开销 1~3ms/连接）；生产可改回 QueuePool 但必须配合
        # 显式 connect-event 强制 SET SESSION，并验证不复发。
        kwargs["poolclass"] = NullPool
        kwargs["isolation_level"] = "READ COMMITTED"
        kwargs["connect_args"] = {
            "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "autocommit": True,
        }

    new_engine = create_async_engine(settings.database_url, **kwargs)

    if not _is_sqlite(settings.database_url):

        @event.listens_for(new_engine.sync_engine, "connect")
        def _mysql_force_read_committed(dbapi_conn: Any, _conn_record: Any) -> None:
            """每个新建 MySQL 连接握手后立即强制 READ COMMITTED。

            为什么不能只靠 connect_args.init_command：
            实测 aiomysql 0.3 + SA 2.0 在某些路径下 init_command 会被
            后续的 SET autocommit / SET TRANSACTION 行为覆盖，导致首条
            事务仍然落在 REPEATABLE READ。这里在 SA 的 connect 事件里
            再补一次显式 SET SESSION，并提前 ROLLBACK 清空 aiomysql
            连接握手期遗留的隐式事务，确保新连接从首条 SELECT 开始就
            稳定处于 READ COMMITTED 快照行为下。
            """
            cur = dbapi_conn.cursor()
            try:
                cur.execute("ROLLBACK")
                cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            finally:
                cur.close()

    if _is_sqlite(settings.database_url):

        @event.listens_for(new_engine.sync_engine, "connect")
        def _sqlite_on_connect(dbapi_conn: Any, _conn_record: Any) -> None:
            """连接级 PRAGMA：保证 WAL、外键、合理超时等核心约束生效。"""
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.execute("PRAGMA temp_store=MEMORY")
            finally:
                cursor.close()

        @event.listens_for(new_engine.sync_engine, "begin")
        def _sqlite_on_begin(conn: Any) -> None:
            """显式发 BEGIN。

            必要性：``isolation_level=None`` 会同时关掉 sqlite3 与 SA
            两侧的隐式事务，必须由我们自己补上 BEGIN，否则事务边界
            会静默失效，跨 session 可见性 bug 会原地复发。
            """
            conn.exec_driver_sql("BEGIN")

    return new_engine


def _build_session_maker(bind_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


class _AsyncSessionMakerProxy:
    """可重绑定的 sessionmaker 代理。

    Celery prefork 模式下，worker 子进程不能继续复用父进程里初始化的
    async engine / sessionmaker。这里保持导入对象稳定，同时允许在子进程
    启动后重新绑定底层 sessionmaker。
    """

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def configure(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncSession:
        return self._maker(*args, **kwargs)


engine = _build_engine()
async_session_maker = _AsyncSessionMakerProxy(_build_session_maker(engine))


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


async def init_db() -> None:
    """创建所有表（开发/迁移用）。"""
    # 确保 ORM 模型已导入，从而注册到 Base.metadata
    import app.models.llm  # noqa: F401  # pylint: disable=unused-import
    import app.models.studio  # noqa: F401
    import app.models.task  # noqa: F401
    import app.models.task_links  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库连接。"""
    await engine.dispose()


def reset_db_runtime() -> None:
    """在 Celery worker 子进程中重建 engine 与 sessionmaker。

    这样可以避免 prefork 继承父进程中的 async engine，导致连接对象和事件循环
    绑定错乱，触发 Future attached to a different loop。
    """

    global engine

    engine = _build_engine()
    async_session_maker.configure(_build_session_maker(engine))
