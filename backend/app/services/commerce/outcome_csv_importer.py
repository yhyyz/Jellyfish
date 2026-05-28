"""StoryOutcome CSV 批量导入服务（W22-T2，P4 Wave B 1/11）。

实现细节：

- 使用 stdlib :mod:`csv` 流式逐行解析（``DictReader``），**不引入 pandas
  / openpyxl**——单文件 5MB 上限场景下 stdlib 完全够用，且能避免大依赖
  侵入容器镜像。
- 通过 mapping profile 把第三方平台中文列名翻译成
  :class:`StoryOutcomeCreate` 字段名；profile 详见
  :mod:`app.schemas.commerce.outcome_csv`。
- 容错策略：单行解析失败 / 校验失败 / 写库失败都不中断整个 batch；失
  败行的 ``row_index`` + ``raw_row`` + 简明 ``reason`` 一起累积进
  ``ImportSummary.errors``。整体仍然返回 200。
- 性能：每累计 200 条成功记录就 ``await self._db.flush()``，让 SQLite /
  MySQL 不会一次性堆 N 条 INSERT 在内存里；最后再统一 commit。
- 不调用 :class:`StoryOutcomeService.create`：那条路径包含"先 SELECT
  variant"等单行额外开销，对批量导入不经济；本 importer 自行做最少必
  要的 variant 存在性预检，并复用同一份业务校验函数。

为什么单独拆 importer 而不扩展 ``StoryOutcomeService``：
    AGENTS.md 第 4 条要求 service 层职责单一；现有 ``outcome_service``
    聚焦"单条 CRUD"，而 CSV 导入涉及"流式解析 + mapping + batch 编排
    + 错误聚合"，是另一类业务编排。拆开后未来若新增"自动同步平台
    API"也能继续在本目录下追加同形 service 而不污染单条 CRUD。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story_formula import StoryOutcome, StoryVariant
from app.models.types import Platform
from app.schemas.commerce.outcome import StoryOutcomeCreate
from app.schemas.commerce.outcome_csv import (
    ImportSummary,
    RowError,
    get_mapping_profile,
)


_BATCH_FLUSH_SIZE = 200
_PERCENT_FIELDS = ("completion_rate_3s", "completion_rate_full")
_INT_FIELDS = ("plays", "interactions", "cart_clicks", "orders")
_FLOAT_FIELDS = ("gmv",)


def _parse_percent_or_decimal(value: str) -> float | None:
    """把 ``"85%"`` / ``"0.85"`` / ``""`` 统一翻译成 ``[0, 1]`` 的 float。

    - 末尾 ``%`` 视为百分比，除以 100 得到小数。
    - 空字符串 / None 视为未回传，返回 ``None``。
    - 非数值字符串原样抛 ``ValueError``，由调用方记到 ``errors``。
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("%"):
        return float(raw[:-1].strip()) / 100.0
    return float(raw)


def _parse_recorded_at(value: str) -> datetime:
    """解析 ``recorded_at`` 字段为 timezone-aware ``datetime``。

    支持两种常见格式：

    * ``YYYY-MM-DD HH:MM:SS`` / ``YYYY-MM-DDTHH:MM:SS``（含或不含 tz）
    * ``YYYY-MM-DD``（视为当日 00:00 UTC）

    naive datetime 一律视为 UTC，与 :class:`StoryOutcomeService` 保持
    一致的口径，避免跨层比较时的时区漂移。
    """
    if value is None:
        raise ValueError("recorded_at 不能为空")
    raw = str(value).strip()
    if not raw:
        raise ValueError("recorded_at 不能为空")
    # 兼容 "YYYY-MM-DD HH:MM:SS"：把空格替换为 T 让 fromisoformat 能识别。
    iso = raw.replace(" ", "T", 1) if "T" not in raw and " " in raw else raw
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_platform(value: str | None) -> str:
    """把 CSV 中的平台值标准化成 :class:`Platform` 枚举值字符串。

    - 空值回退到默认 ``douyin``，与 :class:`StoryOutcomeCreate.platform`
      默认保持一致。
    - 未知值原样返回，让 pydantic 在校验时抛 422，避免静默丢失数据。
    """
    if value is None:
        return Platform.douyin.value
    raw = str(value).strip().lower()
    if not raw:
        return Platform.douyin.value
    return raw


def _translate_row(
    raw: dict[str, str],
    mapping: dict[str, str],
) -> dict[str, Any]:
    """按 mapping profile 把 CSV 一行 dict 翻译成 StoryOutcomeCreate 字段 dict。

    - 列名统一 strip 处理（避免导出文件附带 BOM 或空格导致 miss）。
    - 同一字段名只保留第一个非空值（兼容部分平台 CSV 含双语 header）。
    - 数值字段做轻量类型转换；完播率字段同时识别 "85%" / "0.85"。
    """
    translated: dict[str, Any] = {}
    for raw_key, raw_value in raw.items():
        if raw_key is None:
            continue
        key = raw_key.strip().lstrip("\ufeff")
        if not key:
            continue
        target = mapping.get(key) or mapping.get(key.lower())
        if not target:
            continue
        if target in translated and translated[target] not in (None, "", 0):
            continue
        if target == "platform":
            translated[target] = _normalize_platform(raw_value)
            continue
        if target in _PERCENT_FIELDS:
            translated[target] = _parse_percent_or_decimal(raw_value)
            continue
        if target in _INT_FIELDS:
            text = (raw_value or "").strip()
            translated[target] = int(text) if text else 0
            continue
        if target in _FLOAT_FIELDS:
            text = (raw_value or "").strip()
            translated[target] = float(text) if text else 0.0
            continue
        if target == "recorded_at":
            translated[target] = _parse_recorded_at(raw_value)
            continue
        # variant_id / notes 等字符串字段
        translated[target] = (raw_value or "").strip() if raw_value is not None else ""
    return translated


def _validate_business_rules(payload: StoryOutcomeCreate) -> None:
    """对解析后的 payload 做与 :class:`StoryOutcomeService` 一致的兜底校验。

    schema 已经强制 ``gmv >= 0`` / ``rate ∈ [0,1]``，这里只补一个
    schema 无法表达的规则——``recorded_at`` 不允许超过当前时间（容许
    60s 客户端时钟漂移），与单条创建路径的语义保持一致。
    """
    now = datetime.now(timezone.utc)
    if payload.recorded_at.tzinfo is None:
        recorded = payload.recorded_at.replace(tzinfo=timezone.utc)
    else:
        recorded = payload.recorded_at
    if recorded > now + timedelta(seconds=60):
        raise ValueError("recorded_at 不能超过当前时间")


def _format_validation_error(exc: ValidationError) -> str:
    """把 pydantic ``ValidationError`` 压缩成单行中文提示。

    导入场景下不需要把每个 loc/msg 全列出来——大多数错误用户关心的是
    "哪个字段、什么原因"，因此只取首条错误简明展示。
    """
    errors = exc.errors()
    if not errors:
        return "字段校验失败"
    first = errors[0]
    loc = ".".join(str(x) for x in first.get("loc", ()))
    msg = first.get("msg", "字段校验失败")
    return f"{loc}: {msg}" if loc else msg


class OutcomeCsvImporter:
    """``story_outcomes`` 表的批量 CSV 导入编排。

    用法：

    .. code-block:: python

        importer = OutcomeCsvImporter(db, mapping_profile="douyin")
        summary = await importer.import_stream(uploaded_file.file)

    """

    def __init__(self, db: AsyncSession, mapping_profile: str | None = None) -> None:
        """绑定异步会话与 mapping profile。

        Args:
            db: 已开启的异步会话；commit 由路由层 ``Depends(get_db)`` 兜底。
            mapping_profile: ``"douyin"`` / ``"xiaohongshu"`` / ``"default"``；
                不区分大小写；未知名字回退到 ``default``。
        """
        self._db = db
        self._profile_name = (mapping_profile or "default").lower()
        self._mapping = get_mapping_profile(self._profile_name)
        self._known_variants: set[str] = set()

    async def _is_variant_known(self, variant_id: str) -> bool:
        """惰性缓存 + DB 查询判断 variant 是否存在。

        批量导入往往同一 variant 对应多行；因此把已确认存在的 variant
        缓存到 ``self._known_variants``，避免重复 SELECT。
        """
        if variant_id in self._known_variants:
            return True
        stmt = select(StoryVariant.id).where(StoryVariant.id == variant_id)
        found = (await self._db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            self._known_variants.add(variant_id)
            return True
        return False

    async def import_stream(self, stream: Any) -> ImportSummary:
        """从可读字节流中流式解析 CSV 并写入 DB，返回汇总。

        参数说明：

        Args:
            stream: 任何提供 ``read`` 的对象；FastAPI ``UploadFile.file``
                即可直接传入。函数内部会用 :class:`io.TextIOWrapper`
                做按行解码，**不会 read() 整个文件到内存**——这正是流式处理
                的关键。

        Returns:
            :class:`ImportSummary`，含 ``inserted`` / ``failed`` /
            ``errors`` 等字段。

        关键内部逻辑：

        1. 用 ``TextIOWrapper(..., encoding="utf-8-sig")`` 处理 BOM。
        2. ``csv.DictReader`` 按行 yield；每个 row 走 mapping → pydantic
           → 业务校验 → DB add 流程。
        3. 任一阶段抛错都把行记到 ``errors``，**不 abort**。
        4. 每 ``_BATCH_FLUSH_SIZE`` 条 ``flush()`` 一次缓解内存。
        """
        text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")  # type: ignore[arg-type]
        reader = csv.DictReader(text_stream)

        errors: list[RowError] = []
        inserted = 0
        total_rows = 0
        pending = 0

        # row_index 从 2 开始（header 行 = 1）
        for raw_row in reader:
            total_rows += 1
            row_index = reader.line_num  # 包含 header 的真实行号
            try:
                payload_dict = _translate_row(raw_row, self._mapping)
                if not payload_dict.get("variant_id"):
                    raise ValueError("variant_id 不能为空")
                if "recorded_at" not in payload_dict:
                    raise ValueError("recorded_at 不能为空")
                payload = StoryOutcomeCreate.model_validate(payload_dict)
                _validate_business_rules(payload)

                if not await self._is_variant_known(payload.variant_id):
                    raise ValueError(f"variant_id={payload.variant_id} 不存在")

                outcome = StoryOutcome(
                    variant_id=payload.variant_id,
                    platform=payload.platform.value
                    if isinstance(payload.platform, Platform)
                    else str(payload.platform),
                    plays=payload.plays,
                    completion_rate_3s=payload.completion_rate_3s,
                    completion_rate_full=payload.completion_rate_full,
                    interactions=payload.interactions,
                    cart_clicks=payload.cart_clicks,
                    orders=payload.orders,
                    gmv=payload.gmv,
                    notes=payload.notes,
                    raw_payload=dict(raw_row),
                    recorded_at=payload.recorded_at,
                )
                self._db.add(outcome)
                inserted += 1
                pending += 1
                if pending >= _BATCH_FLUSH_SIZE:
                    await self._db.flush()
                    pending = 0
            except ValidationError as exc:
                errors.append(
                    RowError(
                        row_index=row_index,
                        raw_row=dict(raw_row),
                        reason=_format_validation_error(exc),
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(
                    RowError(
                        row_index=row_index,
                        raw_row=dict(raw_row),
                        reason=str(exc) or exc.__class__.__name__,
                    )
                )

        if pending > 0:
            await self._db.flush()

        return ImportSummary(
            total_rows=total_rows,
            inserted=inserted,
            failed=len(errors),
            mapping_profile=self._profile_name,
            errors=errors,
        )


__all__ = ["OutcomeCsvImporter"]
