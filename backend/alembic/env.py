"""Alembic 迁移环境配置。

从 app.config.settings 动态获取数据库 URL，
将异步驱动替换为同步驱动后用于迁移执行。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.config import settings
from app.core.db import Base

# 确保所有 ORM 模型已导入，以便 autogenerate 能检测到完整 metadata
import app.models.llm  # noqa: F401
import app.models.studio  # noqa: F401
import app.models.task  # noqa: F401
import app.models.task_links  # noqa: F401
import app.models.compliance  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """将应用配置中的异步数据库 URL 转换为同步驱动版本。

    Alembic 不需要 async driver，因此：
    - aiomysql -> pymysql
    - aiosqlite -> 去掉（使用内置 sqlite3）
    """
    url = str(settings.database_url)
    url = url.replace("sqlite+aiosqlite", "sqlite")
    url = url.replace("+aiomysql", "+pymysql")
    url = url.replace("+aiosqlite", "")
    return url


def run_migrations_offline() -> None:
    """以 offline 模式运行迁移（无需真实数据库连接）。

    仅生成 SQL 脚本，不实际执行。
    """
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以 online 模式运行迁移（连接真实数据库）。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
