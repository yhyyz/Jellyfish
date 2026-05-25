"""W14-T2 商品参考图生成服务（image_generation pipeline 适配层）。

为什么存在
==========

剧情带货链路在 W14 阶段需要把 ``Product`` 的卖点 / 品牌 / 风格喂给图像
模型，自动生产可入库的“商品参考图”。该能力技术上完全复用 W2 的
``image_generation`` task_kind 与 worker（registry 已注册），但商品域
有几条业务约束必须**在入队前**完成、不能丢给 worker：

1. **校验商品存在**：worker 收到 ``relation_entity_id`` 后只会原样查
   ``ProductImage`` 行，对不存在的 ``Product`` 没有人类可读的 404；
2. **选择正确模板**：``view_angle=front`` 命中 ``product_image_front_v1``，
   其余角度命中 ``product_image_other_v1``；若 ``Product.prompt_template_id``
   非空，则始终优先使用该自定义模板（用户主动覆写优先级最高）；
3. **渲染 Jinja 模板**：把 ``product`` / ``style`` / ``view_angle`` 三个
   变量塞进 ``StrictUndefined`` 环境，提前在 service 层暴露“未声明变量”
   类问题，而不是把异常推到 worker 让任务静默失败；
4. **构造可被 worker 直接消费的 ``run_args``**：与
   :func:`app.services.studio.image_task_runner.create_image_task_and_link`
   保持一致的 schema（``provider`` / ``api_key`` / ``base_url`` / ``input``
   /``relation_type`` / ``relation_entity_id``），让 W2 worker 不需要任何
   分支即可消费本服务投递的任务。

设计要点
========

- **复用 commerce/task_dispatch 的入队范式**：直接用
  :data:`app.core.celery_app.celery_app` ``send_task`` 投递 ``task.execute``
  到 ``fast`` 队列；不过 image_generation worker SLA 与 fast 队列匹配
  （≤30 分钟），与 W6-T3 的 3 个 commerce 任务共享路由。
- **不在本层 commit**：与 ``CommerceTaskDispatchService`` 一致，事务由
  :func:`app.dependencies.get_db` 上下文统一收口，确保 ``GenerationTask``
  行落盘后才会被 worker 消费。
- **不修改 image_generation worker（W14-T2 锁外）**：``relation_type`` 暂
  时使用 ``product_image``，``relation_entity_id`` 写商品 ID。当前 worker
  的 ``_persist_images_to_assets`` 不识别该 relation_type，因此本任务在
  W2 后续扩展前**只完成图像产出 + 写 FileItem**，不会自动落 ProductImage 行；
  W2 计划在后续 wave 内按 ``relation_type=="product_image"`` 分支补齐
  ``ProductImage`` 持久化。本服务因此只承诺 “入队 + payload 正确”。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models.commerce_assets import Product
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import AssetViewAngle, PromptCategory
from app.services.common import entity_not_found
from app.services.studio.builtin_prompts import render_template

#: ``image_generation`` task_kind，与 worker registry 注册项保持一致。
TASK_KIND_IMAGE_GENERATION = "image_generation"

#: ``front`` 视角默认命中的内置模板 ID（W3-T1 seed）。
DEFAULT_FRONT_TEMPLATE_ID = "product_image_front_v1"

#: 非 ``front`` 视角默认命中的内置模板 ID（W3-T1 seed）。
DEFAULT_OTHER_TEMPLATE_ID = "product_image_other_v1"

#: Celery 统一执行入口；worker 通过 ``GenerationTask.task_kind`` 二级路由。
_CELERY_ENTRY_TASK = "task.execute"

#: 投递队列：image_generation worker SLA 在 30 min 内，与 ``fast`` 队列匹配。
_DEFAULT_QUEUE = "fast"

#: 本服务在 ``run_args`` 中使用的 ``relation_type``。worker 当前不持久化
#: ``ProductImage``；后续 wave 会按该值在 ``_persist_images_to_assets`` 内
#: 增补 ``product_image`` 分支（写 ``ProductImage`` 行 + ``FileUsage``）。
_RELATION_TYPE = "product_image"


def _build_product_render_payload(product: Product) -> dict[str, Any]:
    """把 ``Product`` ORM 对象拍平成 Jinja 渲染上下文。

    为什么单独抽：
        - ``StrictUndefined`` 模式下，模板里的 ``{{ product.x }}`` 任何字段
          缺失都会触发 ``UndefinedError``，渲染面板无法定位真实问题。
          这里统一一次把所有可能被引用的字段补齐成纯 Python 标量 / 列表 /
          字典，避免暴露 SQLAlchemy lazy 属性 + Enum 实例给 Jinja。
        - 单元测试可单独断言这层映射，与 image_generation 入队解耦。

    Returns:
        可直接喂给 :func:`render_template` 的 ``product`` 上下文 dict。
    """

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category.value if hasattr(product.category, "value") else str(product.category),
        "description": product.description,
        "price_anchor": product.price_anchor,
        "sku": product.sku,
        "selling_points": list(product.selling_points or []),
        "pain_points_solved": list(product.pain_points_solved or []),
        "target_audience": dict(product.target_audience or {}),
        "catchphrases": list(product.catchphrases or []),
        "competitor_names": list(product.competitor_names or []),
        "visual_style": product.visual_style.value if hasattr(product.visual_style, "value") else str(product.visual_style),
        "style": product.style.value if hasattr(product.style, "value") else str(product.style),
    }


def _normalize_view_angle(view_angle: str) -> str:
    """把入参视角规范化为 ``AssetViewAngle`` 的枚举值字符串。

    入参可能来自 OpenAPI 客户端（如 ``"front"`` 小写）或前端表单（如
    ``"FRONT"``）；统一映射到上游枚举值字符串（``"FRONT"``）以保持与
    ``ProductImage.view_angle`` 列写入值一致，避免下游做任意大小写比较。

    Raises:
        HTTPException 400: 入参不是合法的 :class:`AssetViewAngle` 值。
    """

    if not view_angle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="view_angle is required",
        )

    raw = str(view_angle).strip()
    # 兼容大小写：枚举值定义为 ``FRONT`` 等大写
    candidates = {raw, raw.upper(), raw.lower()}
    for candidate in candidates:
        try:
            return AssetViewAngle(candidate).value
        except ValueError:
            continue
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid view_angle: {view_angle!r}",
    )


class ProductImageGenerationService:
    """商品参考图生成入队服务。

    职责边界（与 ``AGENTS.md`` 第 4 条对齐）：

    - 收参与最外层校验：保留在路由层（FastAPI / Pydantic）；
    - **本 service**：业务级校验（商品存在）、模板解析、Jinja 渲染、
      ``run_args`` 组装、``GenerationTask`` 落表、Celery 投递；
    - 实际图像生成与下游持久化：image_generation worker（W2 范畴，**锁定**）。

    实例语义：
        每次 HTTP 请求由 ``Depends(get_db)`` 提供新的 :class:`AsyncSession`；
        本类无状态，方法均为 ``async``。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def enqueue_product_image_generation(
        self,
        *,
        product_id: str,
        view_angle: str = AssetViewAngle.front.value,
        quality_level: str = "HIGH",
        reference_file_id: str | None = None,
    ) -> dict[str, Any]:
        """触发商品参考图生成任务。

        步骤：
            1. ``Product`` 存在性校验 → 不存在抛 404；
            2. 解析使用的提示词模板（自定义优先 / 否则按 view_angle 选默认）；
            3. 用 ``StrictUndefined`` Jinja 渲染出 image_generation 的 prompt 文本；
            4. 组装与 ``image_task_runner`` 一致 schema 的 ``run_args``；
            5. 写 ``GenerationTask`` 行（pending）+ Celery 投递。

        Args:
            product_id: 目标商品 ID（``Product.id``）。
            view_angle: 视角；由路由层透传，本服务再做规范化与枚举校验。
            quality_level: 画面质量等级；原样写入 ``run_args``，由下游
                ``image_generation`` worker 决定模型档位。
            reference_file_id: 可选参考图 ``FileItem.id``；存在则塞进
                ``run_args.input.images`` 作为图生图基底。

        Returns:
            ``{"task_id", "product_id", "view_angle", "template_used"}``。
        """

        product = await self._load_product_or_404(product_id)
        normalized_view = _normalize_view_angle(view_angle)
        template = await self._resolve_prompt_template(product, normalized_view)
        render_context = self._build_render_context(product, normalized_view)
        prompt_text = render_template(template.content, render_context)

        run_args = self._build_run_args(
            product_id=product_id,
            normalized_view=normalized_view,
            quality_level=quality_level,
            reference_file_id=reference_file_id,
            prompt_text=prompt_text,
            template_id=template.id,
        )

        task_id = await self._persist_and_dispatch(run_args)

        return {
            "task_id": task_id,
            "product_id": product_id,
            "view_angle": normalized_view,
            "template_used": template.id,
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _load_product_or_404(self, product_id: str) -> Product:
        """读取 ``Product`` 行；不存在直接抛 404。"""

        product = await self.db.get(Product, product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        return product

    async def _resolve_prompt_template(
        self,
        product: Product,
        normalized_view: str,
    ) -> PromptTemplate:
        """按优先级解析模板：``Product.prompt_template_id`` > 角度默认。

        - 用户为商品配置了自定义模板时（``Product.prompt_template_id`` 非空）
          始终优先使用，无视 view_angle；
        - 否则：
            * ``view_angle == FRONT`` → ``product_image_front_v1``；
            * 其余角度（``LEFT/RIGHT/BACK/THREE_QUARTER/TOP/DETAIL``）→
              ``product_image_other_v1``。

        当数据库未 seed 默认模板时（极罕见，例如忘记跑 bootstrap），抛 503，
        避免静默走空模板。
        """

        if product.prompt_template_id:
            template = await self.db.get(PromptTemplate, product.prompt_template_id)
            if template is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Product.prompt_template_id refers to missing template: "
                        f"{product.prompt_template_id}"
                    ),
                )
            return template

        if normalized_view == AssetViewAngle.front.value:
            target_id = DEFAULT_FRONT_TEMPLATE_ID
            target_category = PromptCategory.product_image_front
        else:
            target_id = DEFAULT_OTHER_TEMPLATE_ID
            target_category = PromptCategory.product_image_other

        # 优先按 ID 命中（idempotent bootstrap 的默认 id 形态）；若被人工删
        # 改导致 ID 缺失，则回退到 category + is_default=True + is_system 的
        # 等价定位，保持服务韧性。
        template = await self.db.get(PromptTemplate, target_id)
        if template is not None:
            return template

        stmt = (
            select(PromptTemplate)
            .where(
                PromptTemplate.category == target_category,
                PromptTemplate.is_default.is_(True),
            )
            .limit(1)
        )
        fallback = (await self.db.execute(stmt)).scalars().first()
        if fallback is not None:
            return fallback

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Builtin product image template not found: {target_id} "
                f"(category={target_category.value})"
            ),
        )

    @staticmethod
    def _build_render_context(product: Product, normalized_view: str) -> dict[str, Any]:
        """组装 Jinja 渲染上下文。

        ``product_image_front_v1`` 期望 ``product`` + ``style``；
        ``product_image_other_v1`` 期望 ``product`` + ``view_angle``。
        为兼容“自定义模板可能引用任意字段”的情况，这里把两类通用变量都
        提供出来，由 ``StrictUndefined`` 自然丢弃模板未引用的多余键。
        """

        product_payload = _build_product_render_payload(product)
        return {
            "product": product_payload,
            "style": product_payload["style"],
            "view_angle": normalized_view,
        }

    @staticmethod
    def _build_run_args(
        *,
        product_id: str,
        normalized_view: str,
        quality_level: str,
        reference_file_id: str | None,
        prompt_text: str,
        template_id: str,
    ) -> dict[str, Any]:
        """组装传给 image_generation worker 的 ``run_args``。

        与 :func:`app.services.studio.image_task_runner.create_image_task_and_link`
        的 ``run_args`` 形态对齐：

        - ``provider`` / ``api_key`` / ``base_url``：留空字符串占位，由
          worker 在执行时按 ``ModelSettings.default_image_model_id`` 解析；
          这样可以避开“入队时数据库无图片模型 → 入队失败”的早抛错路径，
          保留任务残留以便 UI 展示。
        - ``input``：worker 读取的标准输入，包含 ``prompt`` / ``model``
          / ``target_ratio`` / ``resolution_profile`` / ``purpose`` 等键；
          为兼容当前 worker schema，``model`` 留空（worker 内部解析），
          ``purpose`` 设为 ``"product_image"`` 以便排障识别来源。
        - ``relation_type`` / ``relation_entity_id``：写 ``product_image`` 与
          商品 ID；W2 worker 后续在 ``_persist_images_to_assets`` 内增补
          ``product_image`` 分支即可承接结果。
        - ``render_context``：把模板 ID 与视角等信息写到 ``run_args`` 里，
          便于 worker 落库时回填 ``ProductImage`` 字段（``view_angle`` /
          ``quality_level`` / 来源模板）。
        """

        run_args: dict[str, Any] = {
            "provider": "",
            "api_key": "",
            "base_url": None,
            "relation_type": _RELATION_TYPE,
            "relation_entity_id": product_id,
            "input": {
                "prompt": prompt_text,
                "model": "",
                "target_ratio": None,
                "resolution_profile": None,
                "purpose": "product_image",
            },
            "render_context": {
                "product_id": product_id,
                "view_angle": normalized_view,
                "quality_level": quality_level,
                "template_id": template_id,
            },
        }
        if reference_file_id:
            run_args["input"]["images"] = [
                {"id": reference_file_id, "kind": "reference"}
            ]
        return run_args

    async def _persist_and_dispatch(self, run_args: dict[str, Any]) -> str:
        """落 ``GenerationTask`` 行 + 投递 Celery；返回 task_id。

        与 :class:`CommerceTaskDispatchService._enqueue` 对齐：
            1. 生成 ``uuid4().hex`` 作为任务主键；
            2. 写 ``GenerationTask``（``async_polling`` / pending / progress=0）；
            3. ``flush`` 进 session（不在此处 commit，由请求上下文兜底）；
            4. 显式 ``celery_app.send_task("task.execute", args=[task_id], queue="fast")``。
        """

        task_id = uuid.uuid4().hex
        payload: dict[str, Any] = {
            "task_kind": TASK_KIND_IMAGE_GENERATION,
            "run_args": dict(run_args),
        }
        # ``datetime.now`` 仅作为内部记录占位（``GenerationTask`` 的
        # ``created_at`` 由 ``TimestampMixin`` 自动落表），此处忽略 enqueue 时间。
        _ = datetime.now(timezone.utc)
        row = GenerationTask(
            id=task_id,
            mode=GenerationDeliveryMode.async_polling,
            task_kind=TASK_KIND_IMAGE_GENERATION,
            status=GenerationTaskStatus.pending,
            progress=0,
            payload=payload,
            result=None,
            error="",
        )
        self.db.add(row)
        await self.db.flush()

        # 显式 queue="fast"：与 commerce/task_dispatch 一致，避免后续路由配
        # 置变更把图像任务误落到 slow 队列；同时让单测可直接断言 queue 参数。
        celery_app.send_task(
            _CELERY_ENTRY_TASK,
            args=[task_id],
            queue=_DEFAULT_QUEUE,
        )
        return task_id


__all__ = [
    "DEFAULT_FRONT_TEMPLATE_ID",
    "DEFAULT_OTHER_TEMPLATE_ID",
    "ProductImageGenerationService",
    "TASK_KIND_IMAGE_GENERATION",
]
