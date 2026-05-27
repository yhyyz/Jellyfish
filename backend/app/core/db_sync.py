"""SQLAlchemy 同步引擎与会话。

给 Celery worker 使用，避免在同步 worker 进程里承载 async DB runtime。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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

    做什么：与异步引擎保持同样的 SQLite 连接级 PRAGMA 配置，
    确保 Celery 任务里 sync session 的 WAL / 外键 / 超时等行为
    与 web 进程一致，避免出现 "web 看得到 / worker 看不到" 这类
    跨执行体的可见性差异。

    为什么不复用 db.py 的事件钩子：
    db.py 里钩子是注册到 ``async_engine.sync_engine``（异步引擎内嵌的
    底层同步引擎），不会作用到这里独立创建的 ``Engine`` 实例。
    因此必须在本模块再注册一次 ``connect`` 监听器。
    """
    sync_url = _to_sync_database_url(settings.database_url)
    new_engine = create_engine(
        sync_url,
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
    )

    if _is_sqlite_sync(sync_url):

        @event.listens_for(new_engine, "connect")
        def _sqlite_on_connect(dbapi_conn: Any, _conn_record: Any) -> None:
            """连接级 PRAGMA：与异步引擎保持完全一致的 5 项设置。"""
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=15000")
                cursor.execute("PRAGMA temp_store=MEMORY")
            finally:
                cursor.close()

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
