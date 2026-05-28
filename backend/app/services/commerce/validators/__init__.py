"""Commerce 链路 validator 子包。

放置 LLM 阶段的输出校验器：当 agent 输出违反业务硬约束（如混入禁止
品牌、口吻偏离 archetype 等）时，validator 把问题报为 issues 列表，
配合 :mod:`app.chains.agents._retry` 触发带 guidance 的有限重试。

子模块：
    competitor_filter: 基于 pyahocorasick 的多模式扫描，确保生成文案
        不出现 ``Product.competitor_names`` 中登记的竞品名。
"""

from app.services.commerce.validators.competitor_filter import (
    build_competitor_validator,
    find_competitor_mentions,
)

__all__ = [
    "build_competitor_validator",
    "find_competitor_mentions",
]
