"""commerce/* 异步任务入口的 3 个 POST 路由（W6-T3）。

路由职责（保持瘦身）：
    1. 用 :class:`app.schemas.commerce.tasks.*Request` 自动校验入参；
    2. 通过 :class:`app.services.commerce.task_dispatch.CommerceTaskDispatchService`
       落表 + 投递 Celery；
    3. 把 service 返回的 dict 包成 :class:`TaskEnqueueResponse` 后用统一
       响应壳 ``ApiResponse`` 返回，状态码固定 ``202 Accepted``。

为什么用 202 而不是 200：
    任务入队后并未真正执行完，结果尚未产出；按 RFC 7231 的语义，202 是
    “请求已被接收，处理尚未完成”的最贴切状态码，前端可以借此与“同步
    完成的 200 响应”区分轮询策略。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.tasks import (
    ComplianceCheckRequest,
    ProductExtractRequest,
    ScriptGenerateRequest,
    TaskEnqueueResponse,
)
from app.core.contracts.story import BatchGenerationRequest
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.task_dispatch import CommerceTaskDispatchService

router = APIRouter()


@router.post(
    "/products/extract",
    response_model=ApiResponse[TaskEnqueueResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="入队：商品信息抽取（异步任务）",
)
async def enqueue_product_extract(
    body: ProductExtractRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskEnqueueResponse]:
    """收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。"""

    service = CommerceTaskDispatchService(db)
    payload = await service.enqueue_product_extract(body.model_dump())
    return success_response(
        TaskEnqueueResponse.model_validate(payload),
        code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/script-generate",
    response_model=ApiResponse[TaskEnqueueResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="入队：剧情脚本生成（异步任务）",
)
async def enqueue_script_generate(
    body: ScriptGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskEnqueueResponse]:
    """收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。"""

    service = CommerceTaskDispatchService(db)
    payload = await service.enqueue_script_generate(body.model_dump())
    return success_response(
        TaskEnqueueResponse.model_validate(payload),
        code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/compliance/check",
    response_model=ApiResponse[TaskEnqueueResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="入队：合规检查（异步任务）",
)
async def enqueue_compliance_check(
    body: ComplianceCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskEnqueueResponse]:
    """收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。"""

    service = CommerceTaskDispatchService(db)
    payload = await service.enqueue_compliance_check(body.model_dump())
    return success_response(
        TaskEnqueueResponse.model_validate(payload),
        code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/story-batches",
    response_model=ApiResponse[TaskEnqueueResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="批量生成：一次性入队 N 个 story_script_generate 子任务",
)
async def enqueue_story_batch(
    body: BatchGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskEnqueueResponse]:
    """批量生成入口：把变体网格作为一次性请求落到 ``slow`` 队列上。

    路由职责仍保持瘦身：仅做 Pydantic 校验 + 调 service + 包响应壳；
    “一行变体 -> 一个子 ``story_script_generate`` 任务”的真正编排逻辑
    在 :func:`app.services.commerce.story_video_batch_generate_worker.run_story_video_batch_generate_task`
    里执行，由 worker 在异步链路上完成。
    """

    service = CommerceTaskDispatchService(db)
    payload = await service.enqueue_story_batch(body.model_dump())
    return success_response(
        TaskEnqueueResponse.model_validate(payload),
        code=status.HTTP_202_ACCEPTED,
    )
