"""分镜视觉一致性证据只读路由（W27-T3）。

仅暴露：

- ``GET /api/v1/commerce/shots/{shot_id}/consistency-evidence``：返回分镜
  当前的 ``consistency_score`` + 色档 + 抽样帧 URL + 参考图 URL，供前端
  ``ConsistencyReviewDrawer`` 与 ``ConsistencyBadge`` 直接消费。

按 AGENTS.md 分层约定：

- 路由层只做收参 / 调 service / 包装 ``ApiResponse``；
- 业务在 :mod:`app.services.commerce.shot_consistency_service` 下沉。
- W27-T1 sidecar 已经把 score 写入 ``Shot.consistency_score``，本路由严
  格只读、不重新计算，避免与 worker 重复打 sidecar。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.shot_consistency import ConsistencyEvidenceRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.shot_consistency_service import build_consistency_evidence
from app.services.common import entity_not_found

router = APIRouter()


@router.get(
    "/shots/{shot_id}/consistency-evidence",
    response_model=ApiResponse[ConsistencyEvidenceRead],
    summary="分镜视觉一致性证据（score + 抽样帧 + 参考图）",
)
async def get_shot_consistency_evidence(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ConsistencyEvidenceRead]:
    """返回 shot_id 对应的视觉一致性证据。

    路径参数：

    - ``shot_id``：``Shot.id``，不存在返回 404。

    响应数据：

    - ``score``：``Shot.consistency_score``（``None`` 表示未跑 / 缺参考）。
    - ``status``：色档字面量，按 0.85 / 0.75 阈值映射。
    - ``sampled_frame_urls``：从关联 product 的 ProductImage 拼装的视觉证据
      样本（最多 6 张）；当前 worker 不持久化 ffmpeg 抽帧，待后续 wave
      接入持久化路径后可平滑替换。
    - ``reference_image_url``：与 worker 同源选取（FRONT > THREE_QUARTER）。
    - ``retry_count``：T27-2 重试机制字段；未落地时为 ``None``。
    """

    try:
        payload = await build_consistency_evidence(db, shot_id=shot_id)
    except LookupError as exc:
        # service 用 LookupError 表达 "shot 不存在"，路由层翻译成 404。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Shot"),
        ) from exc
    return success_response(ConsistencyEvidenceRead.model_validate(payload))


__all__ = ["router"]
