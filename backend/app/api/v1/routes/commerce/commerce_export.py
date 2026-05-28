"""``POST /api/v1/commerce/export`` 路由（W23-T2，P4 Wave B）。

把"已经合成好的章节成片按 PlatformExportPreset 转换为平台发布版本"的入口
独立成文件，与 ``commerce/tasks`` 下的 8 个异步任务入口职责并列但语义独立。

路由职责保持瘦身：
    1. :class:`CommerceExportRequest` 自动校验入参（``extra="forbid"``）；
    2. 经 :class:`CommerceTaskDispatchService.enqueue_commerce_export` 落
       ``GenerationTask`` 行（``slow`` 队列，不发 broker 消息）；
    3. **显式 ``await db.commit()``** 与 ``commerce/tasks`` 系列保持一致
       （W19b commit-before-dispatch 契约，避免 worker 拿不到尚未 commit
       的行）；
    4. ``dispatcher.dispatch_after_commit(descriptor)`` 完成投递；
    5. 按 :class:`TaskEnqueueResponse` 序列化 + ``ApiResponse`` 包壳，
       状态码固定 ``202 Accepted``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.commerce_export import CommerceExportRequest
from app.schemas.commerce.tasks import TaskEnqueueResponse
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.task_dispatch import CommerceTaskDispatchService

router = APIRouter()


@router.post(
    "/export",
    response_model=ApiResponse[TaskEnqueueResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="入队：平台导出（按 PlatformExportPreset 转换章节成片，P4 W23）",
)
async def enqueue_commerce_export(
    body: CommerceExportRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskEnqueueResponse]:
    """收参 → 落 ``GenerationTask`` 行 → commit → Celery slow 队列投递 → 返回 task_id。

    触发 ``commerce_export`` worker：把章节成片（``chapter_master_dubbed``）
    按 :class:`PlatformExportPreset` 转换成平台衍生版本（aspect scale+pad +
    水印 / 贴纸 overlay + loudnorm + 编码与容器切换），输出 :class:`FileItem`
    的 ``usage_kind`` 标 ``product_export``。
    """

    service = CommerceTaskDispatchService(db)
    descriptor = await service.enqueue_commerce_export(body.model_dump())
    await db.commit()
    service.dispatch_after_commit(descriptor)
    return success_response(
        TaskEnqueueResponse.model_validate(descriptor, from_attributes=True),
        code=status.HTTP_202_ACCEPTED,
    )
