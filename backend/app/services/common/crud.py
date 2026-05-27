"""通用 CRUD 助手：减少路由层样板代码。"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.common.validators import require_entity

ModelT = TypeVar("ModelT")


async def create_and_refresh(db: AsyncSession, obj: ModelT) -> ModelT:
    """写入对象、提交事务并刷新，返回最新状态。

    为什么必须在 service 层显式 commit 而不是只 flush：
    FastAPI 的 ``Depends(get_db)`` 用 ``yield`` 模式做事务收尾，
    这意味着 ``session.commit()`` 是在 *response 已经通过 ASGI send
    给客户端之后* 才执行的。若只 flush 不 commit，HTTP 201 已经返回，
    客户端立即发起下一条请求；新请求另开 aiomysql 连接做 SELECT，
    会读不到本次写入（连接级 READ COMMITTED 也救不回来 —— 因为本次
    INSERT 此刻物理上根本还没 COMMIT）。表现就是
    "刚 POST 成功的实体下一步 GET/POST 立刻找不到"。
    显式 commit 把可见性边界推到响应之前，彻底消除 race。
    """
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


def patch_model(obj: Any, data: dict[str, Any]) -> Any:
    """将字典字段更新到模型实例。"""
    for field, value in data.items():
        setattr(obj, field, value)
    return obj


async def get_or_404(
    db: AsyncSession,
    model: type[ModelT],
    entity_id: Any,
    *,
    detail: str,
) -> ModelT:
    """获取实体，不存在时抛出 404。"""
    return await require_entity(db, model, entity_id, detail=detail)


async def flush_and_refresh(db: AsyncSession, obj: ModelT) -> ModelT:
    """提交事务并刷新对象，返回最新状态。

    与 ``create_and_refresh`` 同样的可见性原因：必须 commit，不能只
    flush。详见上面的注释。
    """
    await db.commit()
    await db.refresh(obj)
    return obj


async def delete_if_exists(
    db: AsyncSession,
    model: type[Any],
    entity_id: Any,
) -> None:
    """若实体存在则删除并提交事务；不存在时静默返回。"""
    obj = await db.get(model, entity_id)
    if obj is None:
        return
    await db.delete(obj)
    await db.commit()
