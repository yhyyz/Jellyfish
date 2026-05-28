"""第三方调用入口 ``POST /api/v1/public/commerce/generate`` 的 Pydantic schema（W24-T2）。

为什么独立成文件而不是复用 :mod:`app.schemas.commerce.tasks` 内的请求体
-------------------------------------------------------------------

内部 admin 通道（``/api/v1/commerce/*``）的请求体高度结构化、字段繁多
（``ScriptGenerateRequest`` / ``BatchGenerationRequest`` 等），与项目内
``StoryFormula`` / ``StoryProject`` 状态机紧密耦合，不适合直接对外暴露：

- 它们要求调用方提供完整的 ``product`` / ``audience`` 快照、变体网格、
  ``project_id`` / ``chapter_id``，第三方 SaaS 调用方既不熟悉这些内部
  概念，也不需要全部参数；
- 内部 schema 在版本演进中可能频繁加字段，对外契约一旦松动会引发兼容
  风险（比如 ``extra="forbid"`` 改成 allow，老调用方可能因为字段拼写
  问题进入静默降级路径）。

本 schema 只暴露第三方真正关心的 5 个字段：

================  ===========================================================
字段              说明
================  ===========================================================
``product_id``    商品主键，必填，调用方必须先在 admin UI 完成商品入库
``formula_id``    剧情公式 ID（``underdog_triumph`` 等），必填
``archetype``     可选品牌人格原型；为空时由 worker 走默认值
``platform_preset_id``  可选 W23-T1 :class:`PlatformExportPreset` ID
``variant_count`` 一次调用希望产出的变体数（1-6，默认 1）
================  ===========================================================

为什么 ``variant_count`` 上限是 6
--------------------------------

P4 P0 的对外 SLA 把单次调用钳制在“分钟级 + 不超过 6 路并发”，避免单
租户压垮整条 ``slow`` 队列；future wave 可以根据 ``api_key_quota.daily_limit``
做差异化（VIP 给到 10、普通 6、试用 3），届时把硬常量改成基于 quota
的动态上限即可。

为什么 ``estimated_eta_sec`` 用 ``variant_count × 60``
-----------------------------------------------------

线上 ``story_video_batch_generate`` worker 历史 P50 单变体耗时约 45-60s
（含 LLM 改写 + ffmpeg pipeline），按 60s 给前端一个略保守但稳定的预
估值；客户端在轮询 :func:`app.api.v1.routes.public.tasks.get_public_task_status`
时可以基于此做超时兜底。本字段仅作 *提示*，真实完成时间以任务状态机
（``status==succeeded``）为准。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PublicGenerateRequest(BaseModel):
    """``POST /api/v1/public/commerce/generate`` 的请求体。

    Attributes:
        product_id: 目标商品主键；必须先在 admin 通道入库，否则 endpoint
            返回 404（而非静默 placeholder），强制调用方按规范注册商品。
        formula_id: :class:`app.models.story_formula.StoryFormula` 主键；
            未注册的 ``formula_id`` 同样返回 404。
        archetype: 可选品牌人格原型字符串；为空时由 worker 取项目默认。
            schema 层不约束取值范围，下游 worker 会按 brand_archetypes
            注册表做降级处理。
        platform_preset_id: 可选 :class:`PlatformExportPreset` 主键，用于
            约定输出画幅 / 时长 / 字幕样式；不传时 worker 走章节级默认。
        variant_count: 一次调用产出的变体数；P4 P0 钳制在 1-6 区间，避免
            单租户阻塞批量队列。

    设计注释：

    - ``model_config = ConfigDict(extra="forbid")`` 与既有 commerce
      请求体一致，避免老调用方误传字段被静默吞掉，对外契约无歧义；
    - 字段全部使用 ``Field(...)`` 的显式约束（``min_length``、``ge``、
      ``le``）以便 FastAPI 自动产出 422 + 详细 JSON Schema，第三方调
      用方不需要看后端代码就能知道每个字段的取值范围。
    """

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        ...,
        min_length=1,
        description="目标商品主键（必须先在 admin 通道入库；不存在 → 404）",
    )
    formula_id: str = Field(
        ...,
        min_length=1,
        description="剧情公式 ID（如 underdog_triumph；不存在 → 404）",
    )
    archetype: str | None = Field(
        default=None,
        description="可选品牌人格原型；为空时由 worker 取项目默认值",
    )
    platform_preset_id: str | None = Field(
        default=None,
        description="可选 PlatformExportPreset ID；不传时走章节级默认",
    )
    variant_count: int = Field(
        default=1,
        ge=1,
        le=6,
        description="一次调用希望产出的变体数；钳制在 1-6 区间（P4 P0 SLA）",
    )


class PublicGenerateResponse(BaseModel):
    """``POST /api/v1/public/commerce/generate`` 的响应壳。

    Attributes:
        task_id: 入队后落到 :class:`app.models.task.GenerationTask` 的主键，
            调用方用它去 ``GET /api/v1/public/commerce/tasks/{id}`` 拉状态。
        status: 入队后的初始状态，固定 ``"queued"``；与内部
            :class:`app.schemas.commerce.tasks.TaskEnqueueResponse` 的
            ``"pending"`` 区分——对外语义统一为"队列已收下"，避免暴露
            内部 ``GenerationTaskStatus`` 枚举字面值。
        estimated_eta_sec: 预估完成时间（秒），基于
            ``variant_count × 60`` 估算；仅作前端轮询超时兜底参考，真实
            完成时间以任务状态机为准。

    设计注释：

    - 不暴露 ``task_kind`` / ``enqueued_at`` / ``queue`` 等内部字段，与
      :class:`app.schemas.public.task_status.PublicTaskStatusRead` 的
      "最小表面"原则保持一致；
    - ``model_config = ConfigDict(extra="forbid")`` 防止后续 wave 误把
      内部字段透传上来。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(
        ...,
        description="任务 ID（GenerationTask.id，hex 形式）",
    )
    status: str = Field(
        default="queued",
        description="入队后的初始状态，固定为 'queued'",
    )
    estimated_eta_sec: int = Field(
        ...,
        ge=0,
        description="预估完成时间（秒）；基于 variant_count × 60 估算",
    )


__all__ = ["PublicGenerateRequest", "PublicGenerateResponse"]
