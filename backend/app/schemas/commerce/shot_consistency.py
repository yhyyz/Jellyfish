"""分镜视觉一致性证据响应 schema（W27-T3）。

只读 DTO，配套 ``GET /api/v1/commerce/shots/{shot_id}/consistency-evidence``。
对应 W27-T1 的 DINOv2 sidecar 已落到 ``Shot.consistency_score``，本 schema
负责把数值 + 状态色档 + 抽样帧 / 参考图 URL 拼成前端
``ConsistencyReviewDrawer`` 直接消费的形态。

字段语义：

- ``score``: 现存的 ``Shot.consistency_score``（可空），数值区间 ``[-1, 1]``，
  通常落 ``[0, 1]``。``None`` 表示 sidecar 还没跑过 / 缺 reference / 抽帧失
  败，与数值 ``0.0`` 区分。
- ``status``: 由后端按统一阈值映射（与前端 Badge 一致）：

  * ``score >= 0.85`` → ``"green"``
  * ``0.75 <= score < 0.85`` → ``"amber"``
  * ``score < 0.75`` → ``"red"``
  * ``score is None`` → ``"unknown"``

  对前端属于"信号语义"，避免颜色阈值在 UI 与后端各自维护造成漂移。

- ``sampled_frame_urls``: 用于 PreviewGroup 横向展示的抽样帧 URL。
  当前 worker 不持久化 ffmpeg 抽帧产物（短期诊断价值有限），因此后端
  从 Shot 关联的 ``ProductImage`` 集合中选取多角度图片作为视觉证据样本，
  上限 6 张；待后续 wave 补持久化路径后可平滑切换为真实抽样帧。
- ``reference_image_url``: 与 worker 选取参考图的优先级一致（FRONT 优先，
  THREE_QUARTER 兜底）；缺失时为 ``None``，前端进入空态分支。
- ``retry_count``: T27-2 重试机制如果引入了字段则可消费，本任务允许
  ``None`` 占位避免与并行任务冲突。
- ``reference_view_angle``: 当前选定的参考图视角，便于 UI 在 drawer 头
  部标注 "front / three_quarter / 缺参考"。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


#: 状态色档字面量；与 ``ConsistencyBadge`` 保持单一真相来源。
ConsistencyStatus = Literal["green", "amber", "red", "unknown"]


class ConsistencyEvidenceRead(BaseModel):
    """分镜视觉一致性证据响应。

    仅暴露读所需的字段，不在响应里塞 reason / debug 信息（保留 sidecar
    debug 走 task system 路径）。
    """

    model_config = ConfigDict(from_attributes=False)

    shot_id: str = Field(..., description="镜头 ID")
    score: float | None = Field(
        None,
        description=(
            "DINOv2 cosine similarity（[-1, 1]，常落 [0, 1]）；NULL 表示未"
            "跑过 / 缺 reference / sidecar 不可达"
        ),
    )
    status: ConsistencyStatus = Field(
        ...,
        description=(
            "色档：green(>=0.85) / amber([0.75,0.85)) / red(<0.75) / "
            "unknown(score=null)"
        ),
    )
    sampled_frame_urls: list[str] = Field(
        default_factory=list,
        description=(
            "抽样帧 URL 列表（最多 6 张）；当前从 Shot 关联 ProductImage "
            "拼装作为视觉证据样本，未来可切换为 worker 持久化的真实抽样帧"
        ),
    )
    reference_image_url: str | None = Field(
        None,
        description=(
            "参考图 URL；与 worker 一致取 FRONT / THREE_QUARTER 优先级，"
            "缺失时为 None"
        ),
    )
    reference_view_angle: str | None = Field(
        None,
        description="参考图视角（front / three_quarter / ...），便于 UI 标注",
    )
    retry_count: int | None = Field(
        None,
        description=(
            "已重试次数；T27-2 引入重试机制后会写入实际值，未引入时保持 "
            "None 占位（前端按 None 隐藏 '已重试 N 次' 标签）"
        ),
    )


__all__ = ["ConsistencyEvidenceRead", "ConsistencyStatus"]
