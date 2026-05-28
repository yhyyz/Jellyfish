"""StoryOutcome CSV 批量导入相关的 schema（W22-T2，P4 Wave B 1/11）。

为 ``POST /api/v1/commerce/outcomes/import`` 提供：

- mapping profile 常量定义：把抖音 / 小红书等平台的中文导出列名映射到
  :class:`StoryOutcomeCreate` 字段名；用 ``dict`` 显式列出而非动态推断，
  便于后续以"加一行映射"的方式扩展平台。
- 响应 DTO：``RowError`` 描述单行失败，``ImportSummary`` 描述整体结果。

所有 DTO 都遵循 ``ApiResponse`` 包壳约定（路由层再用 ``success_response``
裹外层），本文件不引入业务逻辑或副作用。
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Mapping profiles：第三方平台 CSV 列名 → StoryOutcomeCreate 字段
# ---------------------------------------------------------------------------
#
# 设计取舍：
#
# * 不做"动态嗅探"——明确的字典更利于追踪平台变更；新增平台只需追加
#   一条常量与 ``MAPPING_PROFILES`` 项。
# * value 端为 :class:`StoryOutcomeCreate` 的 *字段名*（snake_case），
#   service 层直接把 row 转成 dict 后用 ``StoryOutcomeCreate.model_validate``
#   做二次校验。
# * 同时允许 *英文* fallback：很多平台导出会附带英文 alias（"plays"），
#   这样 default profile 下也能直接消费。

DOUYIN_MAPPING: Final[dict[str, str]] = {
    "变体ID": "variant_id",
    "变体id": "variant_id",
    "variant_id": "variant_id",
    "平台": "platform",
    "platform": "platform",
    "播放量": "plays",
    "plays": "plays",
    "3秒完播率": "completion_rate_3s",
    "3 秒完播率": "completion_rate_3s",
    "completion_rate_3s": "completion_rate_3s",
    "完播率": "completion_rate_full",
    "completion_rate_full": "completion_rate_full",
    "互动量": "interactions",
    "点赞数": "interactions",
    "interactions": "interactions",
    "加购点击": "cart_clicks",
    "cart_clicks": "cart_clicks",
    "订单数": "orders",
    "orders": "orders",
    "GMV": "gmv",
    "gmv": "gmv",
    "备注": "notes",
    "notes": "notes",
    "记录时点": "recorded_at",
    "recorded_at": "recorded_at",
    "数据日期": "recorded_at",
}

XHS_MAPPING: Final[dict[str, str]] = {
    "变体ID": "variant_id",
    "笔记ID": "variant_id",
    "variant_id": "variant_id",
    "平台": "platform",
    "platform": "platform",
    "曝光": "plays",
    "曝光量": "plays",
    "plays": "plays",
    "3秒完播率": "completion_rate_3s",
    "completion_rate_3s": "completion_rate_3s",
    "完播率": "completion_rate_full",
    "completion_rate_full": "completion_rate_full",
    "互动数": "interactions",
    "interactions": "interactions",
    "加购点击": "cart_clicks",
    "cart_clicks": "cart_clicks",
    "订单数": "orders",
    "orders": "orders",
    "GMV": "gmv",
    "成交金额": "gmv",
    "gmv": "gmv",
    "备注": "notes",
    "notes": "notes",
    "数据日期": "recorded_at",
    "recorded_at": "recorded_at",
}

DEFAULT_MAPPING: Final[dict[str, str]] = {
    "variant_id": "variant_id",
    "platform": "platform",
    "plays": "plays",
    "completion_rate_3s": "completion_rate_3s",
    "completion_rate_full": "completion_rate_full",
    "interactions": "interactions",
    "cart_clicks": "cart_clicks",
    "orders": "orders",
    "gmv": "gmv",
    "notes": "notes",
    "recorded_at": "recorded_at",
}


MAPPING_PROFILES: Final[dict[str, dict[str, str]]] = {
    "douyin": DOUYIN_MAPPING,
    "xiaohongshu": XHS_MAPPING,
    "default": DEFAULT_MAPPING,
}


def get_mapping_profile(name: str | None) -> dict[str, str]:
    """按名字读取 mapping profile；未知名字回退 ``default``。

    Args:
        name: profile 名（``douyin`` / ``xiaohongshu`` / ``default``）；
            None 或空字符串视为 ``default``。

    Returns:
        从 CSV 列名到 ``StoryOutcomeCreate`` 字段名的字典副本，避免调用
        方修改全局常量。
    """
    key = (name or "default").strip().lower()
    return dict(MAPPING_PROFILES.get(key, DEFAULT_MAPPING))


# ---------------------------------------------------------------------------
# 响应 DTO
# ---------------------------------------------------------------------------


class RowError(BaseModel):
    """CSV 单行解析或写库失败的描述。

    保留 ``raw_row`` 是为了让前端可以"原样回显"问题数据，便于运营同学
    比对原 CSV 排查；``reason`` 为简明文案，避免向前端暴露 traceback。
    """

    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(
        ...,
        ge=1,
        description="CSV 中的行号（1-based，包含 header；header 行号为 1）",
    )
    raw_row: dict[str, Any] = Field(
        default_factory=dict,
        description="该行的原始 dict（按 CSV header 解析后），便于前端展示",
    )
    reason: str = Field(..., description="失败原因（中文文案）")


class ImportSummary(BaseModel):
    """批量导入的整体汇总。

    HTTP 200 + summary 即视为一次成功的批处理；失败行不会让整批 abort，
    由 ``errors`` 字段单独展示。前端可基于 ``inserted`` / ``failed``
    决定是否提示成功，并通过 ``errors`` 表格让用户修正错误后重传。
    """

    model_config = ConfigDict(extra="forbid")

    total_rows: int = Field(..., ge=0, description="总数据行（不含 header）")
    inserted: int = Field(..., ge=0, description="成功写入条数")
    failed: int = Field(..., ge=0, description="失败行数 = len(errors)")
    mapping_profile: str = Field(..., description="使用的 mapping profile 名")
    errors: list[RowError] = Field(
        default_factory=list,
        description="逐行失败明细（按 row_index 升序）",
    )


__all__ = [
    "DEFAULT_MAPPING",
    "DOUYIN_MAPPING",
    "ImportSummary",
    "MAPPING_PROFILES",
    "RowError",
    "XHS_MAPPING",
    "get_mapping_profile",
]
