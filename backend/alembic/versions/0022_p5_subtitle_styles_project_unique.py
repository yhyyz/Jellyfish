"""0022 - W30-followup ``subtitle_styles`` ``(project_id, name)`` 唯一约束。

P5 W30-T1（alembic 0019）首次为 ``subtitle_styles`` 增加 ``project_id`` 列时，
出于"MySQL 不支持 partial / functional index"等担忧只在 service 层做
``(project_id, name)`` 唯一性校验。这层校验只能挡住单 transaction 之
内的 happy path：

- 当两个并发请求同时 ``POST /commerce/projects/{p}/subtitle-styles`` 创建
  同 name 的项目级覆盖样式时，service 内 ``SELECT … WHERE project_id=?
  AND name=?`` 都会落空，随后双方都进入 ``INSERT``，留下两条同
  ``(project_id, name)`` 的脏数据。
- 同样的 race 也会出现在 ``PATCH`` rename 后命中已有 name 的场景。

W30-followup #1 在 DB 层补一道闸：

- 给 ``subtitle_styles`` 添加 generated column ``_scope_key VARCHAR(64)``，
  值为 ``COALESCE(project_id, '__system__')``——把"系统级 NULL"映射为字
  面值 ``__system__``，规避 MySQL 不允许在 NULL 行间做 UNIQUE 约束的语
  义；STORED 方式存盘，索引可直接命中。
- 在 ``(_scope_key, name)`` 上加 ``UNIQUE`` 索引
  ``uq_subtitle_styles_scope_name``，让数据库直接 raise IntegrityError
  作为最终兜底。

为什么不直接在 ``(project_id, name)`` 加 UNIQUE：
    MySQL 在 ``UNIQUE (a, b)`` 上视 ``NULL`` 行为"互不冲突"——多条
    ``project_id IS NULL, name='douyin_default'`` 的系统级 seed 行可以
    并存，看似符合需求；但同时也意味着：当用户后续手动把项目级行
    ``project_id`` 改回 NULL（或外部脚本误改）时，DB 不会拦住——一旦
    出现"多条 NULL+同 name"的错乱，``resolve_for_shot`` 会任意选一条
    返回，行为不确定。引入 ``__system__`` sentinel 把所有"系统级"压
    缩到同一个 scope key，让 NULL 行也参与唯一约束，更稳。

为什么 generated column 用 VIRTUAL（MySQL）/ STORED（SQLite）：
    MySQL 8 在 ``ALTER TABLE ADD COLUMN ... STORED`` 加生成列时会触发表
    rebuild，而本表已有 ``fk_subtitle_styles_project_id`` 外键约束，rebuild
    阶段会被 ``Cannot add foreign key constraint`` (Error 1215) 拒绝（这
    是 MySQL 8 的一个已知行为：STORED 生成列的物化过程被 FK validator
    误拦）。VIRTUAL 列不参与表 rebuild，对 FK 透明，且 MySQL 8 完全支
    持在 VIRTUAL 列上建索引，性能等价。SQLite 不区分 VIRTUAL/STORED
    在 ALTER TABLE ADD COLUMN 路径上的代价，但 SQLite 的 VIRTUAL 列不
    能直接 CREATE INDEX，所以 SQLite 走 STORED；测试 fixture 的 SQLite
    schema 也按 STORED 重建。

冲突探测（升级前）：
    在升级真正动表之前，先做一次 ``SELECT`` 探测是否存在违反
    ``(project_id, name)`` 唯一性的脏数据；若有，打 warning 并把行 ID
    列出，但不阻塞升级——因为接下来 generated column 会按 COALESCE 规
    则区分 NULL/非 NULL，对脏数据有可能正好解开冲突；让运维侧拿到
    warning 后再决定是否手动清理。

幂等 / 跨 DB 兼容性：
    - SQLite：``ALTER TABLE ... ADD COLUMN _scope_key … GENERATED ALWAYS AS
      (COALESCE(project_id, '__system__')) STORED``。
    - MySQL：``ALTER TABLE … ADD COLUMN _scope_key VARCHAR(64) AS
      (COALESCE(project_id, '__system__')) STORED``。
    本迁移按 ``op.get_bind().dialect.name`` 分支执行，避免硬编码 dialect。
    downgrade 反向 drop UNIQUE 索引与生成列。

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-29
"""

# pylint: disable=invalid-name,no-member

from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOGGER = logging.getLogger("alembic.runtime.migration")

_INDEX_NAME = "uq_subtitle_styles_scope_name"
_GEN_COLUMN = "_scope_key"


def _detect_existing_conflicts() -> None:
    """升级前 SELECT 探测 ``(project_id, name)`` 重复行；只 warn 不阻塞。

    探测逻辑：
        - 系统级（``project_id IS NULL``）按 ``(NULL, name)`` 分组；
        - 项目级按 ``(project_id, name)`` 分组；
        - 任一分组 count > 1 视为冲突候选。

    若存在冲突分组，把分组键 + 命中的 ID 列表打印到 alembic 日志，提示
    运维侧在升级完成后手动清理（生成列升级路径不会阻塞，但同 scope_key
    重名行会因为 UNIQUE 约束触发 ``IntegrityError`` ——本迁移是 ALTER
    TABLE ADD INDEX，MySQL 会失败，需要先清理）。
    """

    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT COALESCE(project_id, '__system__') AS scope_key, name,
                   GROUP_CONCAT(id) AS ids, COUNT(*) AS cnt
            FROM subtitle_styles
            GROUP BY COALESCE(project_id, '__system__'), name
            HAVING COUNT(*) > 1
            """
        )
        if bind.dialect.name == "mysql"
        else text(
            """
            SELECT COALESCE(project_id, '__system__') AS scope_key, name,
                   GROUP_CONCAT(id, ',') AS ids, COUNT(*) AS cnt
            FROM subtitle_styles
            GROUP BY COALESCE(project_id, '__system__'), name
            HAVING COUNT(*) > 1
            """
        )
    ).all()

    if rows:
        for scope_key, name, ids, cnt in rows:
            _LOGGER.warning(
                "alembic 0022: subtitle_styles duplicate (scope_key=%r, "
                "name=%r) cnt=%s ids=%s — UNIQUE index will FAIL until you "
                "clean these manually",
                scope_key,
                name,
                cnt,
                ids,
            )


def _add_generated_column() -> None:
    """按 dialect 分别 emit 生成列 DDL。

    - MySQL：用 ``VIRTUAL`` 规避 STORED 触发表 rebuild + FK validation
      失败的 Error 1215；MySQL 8 完全支持 VIRTUAL 列上 UNIQUE 索引。
    - SQLite：必须 ``STORED``，因为 SQLite 不允许在 VIRTUAL 列上直接
      ``CREATE INDEX``。
    """

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "mysql":
        op.execute(
            f"ALTER TABLE subtitle_styles ADD COLUMN {_GEN_COLUMN} "
            "VARCHAR(64) AS (COALESCE(project_id, '__system__')) VIRTUAL"
        )
    elif dialect == "sqlite":
        op.execute(
            f"ALTER TABLE subtitle_styles ADD COLUMN {_GEN_COLUMN} "
            "VARCHAR(64) GENERATED ALWAYS AS "
            "(COALESCE(project_id, '__system__')) STORED"
        )
    else:
        op.execute(
            f"ALTER TABLE subtitle_styles ADD COLUMN {_GEN_COLUMN} "
            "VARCHAR(64) GENERATED ALWAYS AS "
            "(COALESCE(project_id, '__system__')) STORED"
        )


def _drop_generated_column() -> None:
    """downgrade 时 drop 生成列；SQLite 需走 batch_alter_table 复制重建。"""

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite 早期版本不支持 ALTER TABLE DROP COLUMN；用 batch 复制重建
        with op.batch_alter_table("subtitle_styles") as batch:
            batch.drop_column(_GEN_COLUMN)
    else:
        op.drop_column("subtitle_styles", _GEN_COLUMN)


def upgrade() -> None:
    """加生成列 ``_scope_key`` 与 ``(_scope_key, name)`` UNIQUE 索引。"""

    _detect_existing_conflicts()
    _add_generated_column()
    op.create_index(
        _INDEX_NAME,
        "subtitle_styles",
        [_GEN_COLUMN, "name"],
        unique=True,
    )


def downgrade() -> None:
    """反向 drop UNIQUE 索引与生成列。"""

    op.drop_index(_INDEX_NAME, table_name="subtitle_styles")
    _drop_generated_column()
