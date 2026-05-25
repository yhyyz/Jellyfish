"""剧情带货（Story-Driven Commerce）业务请求/响应 schemas 包。

P1 阶段聚焦商品（Product / ProductImage）相关 DTO。后续阶段会扩展：
- StoryProject / StoryFormula / StoryVariant 配置 DTO
- ComplianceFinding 读取 DTO

跨层契约（输入/输出 DTO、供应商配置等）统一沉淀在 ``app/core/contracts``，
此处仅承载与 commerce HTTP 接口直接相关的 Pydantic 模型，避免与任务层耦合。
"""

from app.schemas.commerce.product import (
    ProductCreate,
    ProductImageCreate,
    ProductImageRead,
    ProductRead,
    ProductUpdate,
)

__all__ = [
    "ProductCreate",
    "ProductImageCreate",
    "ProductImageRead",
    "ProductRead",
    "ProductUpdate",
]
