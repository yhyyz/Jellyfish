"""W14-T2 商品参考图生成（image_generation pipeline）请求 / 响应模型。

为什么单独成文：
    与 ``product.py`` 中的 CRUD DTO 不同，此处描述的是“**触发异步任务**”的
    入口 / 出口契约。它跨两层使用：

    1. ``POST /api/v1/studio/products/{product_id}/images/generate`` 路由参数；
    2. ``ProductImageGenerationService.enqueue_product_image_generation``
       的返回 payload（再由路由层包成 ``ApiResponse`` 响应壳）。

    把它从 ``product.py`` 拆出来可以：

    - 让 ``ProductCreate`` / ``ProductUpdate`` 这类同步 CRUD DTO 与
      “触发任务”这类异步入口的演进彼此解耦；
    - 在 OpenAPI 中以独立的 schema 名字暴露给前端，避免“同名 ProductImage
      泛指多个含义”的歧义。

设计要点：
    - 请求体 ``ProductImageGenerationRequest`` 使用 ``extra="forbid"``，与
      仓库内其它 commerce 请求 DTO 一致，避免静默忽略未识别字段；
    - ``view_angle`` / ``quality_level`` 选用 :class:`AssetViewAngle` /
      :class:`AssetQualityLevel` 枚举的 *值*（``str``）作为默认入参，
      service 层会再做一次校验（与 ``ProductImage`` 的列定义同步），保持与
      :class:`ProductImageCreate` 的字段语义一致；
    - ``reference_file_id`` 可选：若客户端上传了参考图（如手绘草图、原版
      包装图），会被透传给 image_generation worker 做图生图基底；
    - 响应体只暴露 ``task_id / product_id / view_angle / template_used``
      四个关键字段，避免把 service 层内部 payload（provider/api_key 等）
      透给前端。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.types import AssetQualityLevel, AssetViewAngle


class ProductImageGenerationRequest(BaseModel):
    """触发商品参考图生成的请求体。

    字段说明：
        view_angle:
            视角，沿用 :class:`AssetViewAngle` 枚举值（``FRONT`` /
            ``LEFT`` / ``RIGHT`` / ``BACK`` / ``THREE_QUARTER`` /
            ``TOP`` / ``DETAIL``）。``FRONT`` 命中 ``product_image_front_v1``
            模板，其余角度命中 ``product_image_other_v1`` 模板。
        quality_level:
            质量等级（``LOW`` / ``MEDIUM`` / ``HIGH`` / ``ULTRA``）。
            会被原样写入 ``run_args`` 供下游 worker 决定模型档位与采样
            参数；不影响模板选择。
        reference_file_id:
            可选参考图。若传入，会以 ``[{"id": ..., "kind": "reference"}]``
            形式塞进 ``run_args.input.images``，作为图生图基底；为空表示
            纯文生图。
    """

    model_config = ConfigDict(extra="forbid")

    view_angle: str = AssetViewAngle.front.value
    quality_level: str = AssetQualityLevel.high.value
    reference_file_id: str | None = None


class ProductImageGenerationResponse(BaseModel):
    """商品参考图生成入队响应。

    字段说明：
        task_id:
            ``GenerationTask`` 主键（``uuid4().hex`` 形式）；前端可用其
            轮询 ``/api/v1/tasks/{task_id}`` 获取进度与结果。
        product_id:
            目标商品 ID，回显方便前端绑定 toast / 任务列表。
        view_angle:
            实际生效的视角值（service 会做规范化）。
        template_used:
            实际命中的提示词模板 ID（如 ``product_image_front_v1`` /
            ``product_image_other_v1`` / 或 ``product.prompt_template_id``
            指向的自定义模板）。便于排障与 A/B 验证。
    """

    task_id: str
    product_id: str
    view_angle: str
    template_used: str


__all__ = [
    "ProductImageGenerationRequest",
    "ProductImageGenerationResponse",
]
