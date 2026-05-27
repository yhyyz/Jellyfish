"""SQLAlchemy 同步引擎与会话。

给 Celery worker 使用，避免在同步 worker 进程里承载 async DB runtime。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.db import Base


def _to_sync_database_url(url: str) -> str:
    if url.startswith("mysql+aiomysql://"):
        return "mysql+pymysql://" + url.removeprefix("mysql+aiomysql://")
    if url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + url.removeprefix("sqlite+aiosqlite:///")
    return url


def _is_sqlite_sync(url: str) -> bool:
    """判断同步 URL 是否指向 SQLite。"""
    return url.startswith("sqlite:///") or url.startswith("sqlite://")


def _build_sync_engine() -> Engine:
    """构建给 Celery worker 用的同步引擎。

    做什么：与异步引擎保持同样的 SQLite 连接级 PRAGMA 配置 + 同样的
    isolation_level=None / 显式 BEGIN listener，确保 Celery 任务里 sync
    session 与 web 进程在 WAL 模式下行为一致，**特别是消除 pysqlite 的
    legacy txn 模式导致的 stale read snapshot pin**。

    为什么必须这么做：
    pysqlite (stdlib sqlite3) 默认不会为 SELECT 语句自动发 BEGIN。在
    SQLAlchemy 连接池里，连接归还后下次复用时残留的读事务可能继续
    持有旧的 WAL end mark；新事务读到的数据就是上一次 commit 之前的
    世界。Celery worker 拿到 task_id 后 db.get(GenerationTask, task_id)
    返回 None 就是这个症状。修复方式 = 把驱动放进 autocommit 模式
    (connect_args isolation_level=None)，再用 begin 事件让 SQLAlchemy
    自己显式发 BEGIN，每次都拿到最新快照。

    为什么不复用 db.py 的事件钩子：
    db.py 里钩子是注册到 ``async_engine.sync_engine``（异步引擎内嵌的
    底层同步引擎），不会作用到这里独立创建的 ``Engine`` 实例。
    因此必须在本模块再注册一次。
    """
    sync_url = _to_sync_database_url(settings.database_url)

    kwargs: dict[str, Any] = dict(
        echo=settings.debug,
        future=True,
    )
    if _is_sqlite_sync(sync_url):
        kwargs["connect_args"] = {"isolation_level": None, "timeout": 60.0}
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_pre_ping"] = True

    new_engine = create_engine(sync_url, **kwargs)

    if _is_sqlite_sync(sync_url):

        @event.listens_for(new_engine, "connect")
        def _sqlite_on_connect(dbapi_conn: Any, _conn_record: Any) -> None:
            """连接级 PRAGMA：与异步引擎保持完全一致的 5 项设置。"""
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.execute("PRAGMA temp_store=MEMORY")
            finally:
                cursor.close()

        @event.listens_for(new_engine, "begin")
        def _sqlite_on_begin(conn: Any) -> None:
            """显式发 BEGIN：搭配 isolation_level=None，强制每个事务拿最新 WAL 快照。"""
            conn.exec_driver_sql("BEGIN")

    return new_engine


engine_sync = _build_sync_engine()
sync_session_maker = sessionmaker(
    bind=engine_sync,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

__all__ = [
    "Base",
    "engine_sync",
    "sync_session_maker",
]
