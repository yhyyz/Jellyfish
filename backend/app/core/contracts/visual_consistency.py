"""视觉一致性（DINOv2 sidecar）共享契约（P4 W27-T1）。

为什么单独一个文件：
    - 沿用 ``app.core.contracts`` 的分层约定：跨层使用的 DTO 集中在此，
      ``app.core.integrations.dinov2.client`` 只引用本契约，**不**直接
      import sidecar 那边的 pydantic 模型（隔离 ML stack）；
    - 方便后续 W27-T2 的 threshold engine 复用 ``ConsistencyScoreResult``
      做阈值判定。

字段约束：
    - embedding 维度固定 768（DINOv2 ViT-B/14 cls token），写入 schema
      后改维度需改 sidecar + 本契约 + 数据库迁移三处；
    - similarity 范围 [-1, 1]，但 DINOv2 已 L2 归一，实际值通常落在 [0, 1]。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

#: DINOv2 ViT-B/14 cls token 输出维度。改这里需要同步：
#: - deploy/inference-dinov2/app/model.py 的 _EMBED_DIM
#: - 任何下游存储 / 校验逻辑
DINOV2_EMBED_DIM: int = 768


class EmbedRequest(BaseModel):
    """单图嵌入请求。

    sidecar 同时支持 multipart 文件上传，但 backend 这边走 JSON / form 路径
    更简单：把图片字节先 base64 编码再扔过去，避免 multipart 序列化复杂度。

    image_b64 与 image_url 二选一，全空时由 sidecar 返回 422。
    """

    model_config = ConfigDict(extra="forbid")

    image_b64: Optional[str] = Field(
        default=None,
        description="base64 编码的图片字节（推荐路径，避免 sidecar 二次拉取）",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="可被 sidecar 进程直接 GET 的 URL；仅用于本地调试或 minio 直链",
    )


class EmbedResponse(BaseModel):
    """单图嵌入响应。

    embedding 已 L2 归一，调用方可直接对两个 embedding 做点积得到 cosine。
    """

    model_config = ConfigDict(extra="forbid")

    embedding: list[float] = Field(
        ...,
        description="DINOv2 cls token embedding（L2 归一，长度 == DINOV2_EMBED_DIM）",
    )
    dim: int = Field(..., description="向量维度，恒等于 DINOV2_EMBED_DIM")
    elapsed_ms: int = Field(..., ge=0, description="sidecar 端推理耗时毫秒")


class SimilarityRequest(BaseModel):
    """两图直接计算相似度的请求。

    适用于一次性比对场景；批量比对（如 6 帧 vs 1 reference）走两次 /embed
    再在 backend 侧做均值会更省 sidecar IO。
    """

    model_config = ConfigDict(extra="forbid")

    frame_b64: str = Field(..., min_length=1, description="base64 编码的视频帧")
    reference_b64: str = Field(..., min_length=1, description="base64 编码的参考资产图片")


class SimilarityResponse(BaseModel):
    """两图相似度响应。

    similarity 理论范围 [-1, 1]；DINOv2 视觉相似图通常落在 [0.5, 0.95]。
    """

    model_config = ConfigDict(extra="forbid")

    similarity: float = Field(..., ge=-1.0, le=1.0, description="cosine similarity")
    elapsed_ms: int = Field(..., ge=0, description="sidecar 端推理耗时毫秒")


class ConsistencyScoreResult(BaseModel):
    """``shot_consistency_check`` 任务的最终输出结构。

    用于：
        - worker 侧调 ``GenerationTask.set_result`` 写入；
        - W27-T2 threshold engine 读取后做阈值判定 / 触发回炉；
        - 前端任务中心展示。

    设计要点：
        - ``score`` 可空：缺 reference / 抽帧失败时显式置 ``None``，避免与
          0.0 混淆（cosine 0.0 是合法语义）；
        - ``frame_count`` 实际抽到几帧（可能 < 期望），用于诊断；
        - ``reference_view_angle`` 记录回退路径（front 优先 / three_quarter 兜底）。
    """

    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(..., description="对应的 Shot.id")
    score: Optional[float] = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="cosine similarity；缺 reference 或抽帧 0 帧时为 None",
    )
    frame_count: int = Field(default=0, ge=0, description="实际抽样到的帧数")
    reference_view_angle: Optional[str] = Field(
        default=None,
        description="选中的 ProductImage.view_angle（FRONT / THREE_QUARTER）",
    )
    reference_file_id: Optional[str] = Field(
        default=None,
        description="参考图 FileItem.id；缺 reference 时为 None",
    )
    reason: Optional[str] = Field(
        default=None,
        description="score 为 None 的可读原因（no_reference / no_frames / sidecar_unavailable）",
    )


__all__ = [
    "DINOV2_EMBED_DIM",
    "EmbedRequest",
    "EmbedResponse",
    "SimilarityRequest",
    "SimilarityResponse",
    "ConsistencyScoreResult",
]
