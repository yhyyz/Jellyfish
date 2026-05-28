"""``POST /api/v1/public/commerce/generate`` —— 第三方 SaaS 调用入口（W24-T2）。

职责（保持瘦身）
----------------

1. 中间件 :func:`app.core.api_key_auth.enforce_public_request` 在路由前
   完成 bcrypt 校验 + 配额扣减，命中后把 :class:`ApiKeyQuota` 行注入
   ``request.state.api_key_quota``；本路由首先校验该字段必然存在，避
   免任何"中间件被误删"的回归路径无声跑通；
2. 用 ``db.get`` 校验 ``product_id`` / ``formula_id``（以及可选的
   ``platform_preset_id``）是否真实存在，不存在统一返回 ``404``；
3. 通过 :class:`CommerceTaskDispatchService` 走 ``story_video_batch_generate``
   占位 task_kind 入队（完整 ``commerce_generate`` worker 不在 P4 范围），
   并把 ``api_key_hash`` 显式写入 ``run_args`` —— 这是 T24-3
   ``GET /api/v1/public/commerce/tasks/{id}`` 实现租户隔离的关键依赖；
4. 显式 ``await db.commit()`` 后再 ``dispatch_after_commit``（W19b
   commit-then-send 契约），最后用最小 :class:`PublicGenerateResponse`
   信封返回 ``202 Accepted``。

为什么用 ``story_video_batch_generate`` 占位
--------------------------------------------

P4 W24-T2 范围 *不* 涵盖完整的 ``commerce_generate`` worker 实装：那
需要项目级 ``project_id`` / ``chapter_id`` 锚点、商品/受众快照、变体
网格等结构化输入，会把对外 contract 与内部 worker 调用契约耦合到一
起。当前 wave 只交付"对外入口 + 配额 + 租户隔离"三件事，worker 端先
复用 ``story_video_batch_generate`` 占位，下游只关心 ``task_id`` 与
``api_key_hash`` 这两个字段；后续 wave 会替换为专属 ``commerce_generate``
task_kind 并迁出占位。

为什么把 ``api_key_hash`` 写进 ``run_args`` 而不是单独建一列
-----------------------------------------------------------

参见 :mod:`app.api.v1.routes.public.tasks` 模块 docstring：复用 JSON
列既不引入 schema 变更（不需要 alembic 迁移），又能在多种 task_kind
下保持统一的归属语义；与 T24-3 读取约定对齐——后者从同一路径
``payload["run_args"]["api_key_hash"]`` 读出归属。

为什么 ``estimated_eta_sec = variant_count * 60``
-------------------------------------------------

::class:`PublicGenerateRequest` docstring 详述：60s 是历史 P50 单变体
耗时的略保守估计，作为前端轮询超时兜底的提示值。真实完成时间以
``GET /commerce/tasks/{id}`` 返回的 ``status==succeeded`` 为准。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.commerce_assets import Product
from app.models.platform_export_preset import PlatformExportPreset
from app.models.story_formula import StoryFormula
from app.schemas.common import ApiResponse, success_response
from app.schemas.public.generate import (
    PublicGenerateRequest,
    PublicGenerateResponse,
)
from app.services.commerce.task_dispatch import CommerceTaskDispatchService
from app.services.common import entity_not_found

router = APIRouter()


# 单变体预估耗时（秒）。基于历史 P50 ~45-60s 取保守值。
_ESTIMATED_SECONDS_PER_VARIANT = 60


@router.post(
    "",
    response_model=ApiResponse[PublicGenerateResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="第三方调用入口：提交一次剧情带货生成请求（公开通道）",
)
async def submit_public_generate(
    request: Request,
    body: PublicGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PublicGenerateResponse]:
    """同步入队 + 返回 ``task_id``，让第三方 SaaS 走异步轮询模型。

    分支顺序（与对外契约严格对齐）：

    1. 中间件已保证 ``request.state.api_key_quota`` 必然存在且 active；
       若被误删，这里仍按 401 抛出，让调用方拿到一致的错误信号。
    2. ``Product`` / ``StoryFormula`` 不存在 → 404；可选的
       ``PlatformExportPreset`` 若提供也必须存在，否则同样 404。
    3. 透传到 :class:`CommerceTaskDispatchService`，把 ``api_key_hash``
       写入 ``run_args`` —— **关键**，这是 T24-3 跨租户隔离的前置。
    4. 严格遵守 W19b 的 *commit-then-send* 契约：先 ``await db.commit()``
       再 ``dispatch_after_commit``，避免 ``fast`` / ``slow`` 队列上的
       worker 在外层事务尚未 commit 时拿到 ``None``（B2 race）。

    Args:
        request: FastAPI 请求对象，承载中间件注入的 ``api_key_quota``。
        body: 经 :class:`PublicGenerateRequest` 校验过的请求体。
        db: 数据库会话（``get_db`` 依赖注入）。

    Returns:
        ``ApiResponse[PublicGenerateResponse]`` 包裹的最小信封。

    Raises:
        HTTPException: 401（中间件意外失效）、404（product / formula /
            preset 不存在）。
    """

    quota = getattr(request.state, "api_key_quota", None)
    if quota is None:
        # 防御性兜底：理论上中间件已经保证非空。
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    caller_hash = quota.api_key_hash

    # --- 1) 验证 product 存在 ---
    if await db.get(Product, body.product_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Product"),
        )

    # --- 2) 验证 formula 存在 ---
    if await db.get(StoryFormula, body.formula_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("StoryFormula"),
        )

    # --- 3) 可选：验证 platform_preset 存在 ---
    if body.platform_preset_id is not None:
        preset = await db.get(PlatformExportPreset, body.platform_preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("PlatformExportPreset"),
            )

    # --- 4) 入队（占位 task_kind=story_video_batch_generate）---
    # api_key_hash 必须落在 run_args 里，T24-3 状态查询从同一路径读出归属。
    run_args: dict[str, Any] = {
        "api_key_hash": caller_hash,
        "product_id": body.product_id,
        "formula_id": body.formula_id,
        "archetype": body.archetype,
        "platform_preset_id": body.platform_preset_id,
        "variant_count": body.variant_count,
    }
    service = CommerceTaskDispatchService(db)
    descriptor = await service.enqueue_story_batch(run_args)

    # --- 5) commit-then-send（W19b 契约）---
    await db.commit()
    service.dispatch_after_commit(descriptor)

    response = PublicGenerateResponse(
        task_id=descriptor.task_id,
        status="queued",
        estimated_eta_sec=body.variant_count * _ESTIMATED_SECONDS_PER_VARIANT,
    )
    return success_response(response, code=status.HTTP_202_ACCEPTED)


__all__ = ["router"]
