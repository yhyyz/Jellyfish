"""剧情带货（Story-Driven Commerce）业务请求/响应 schemas 包。

P1 阶段聚焦商品（Product / ProductImage）相关 DTO。后续阶段会扩展：
- StoryProject / StoryFormula / StoryVariant 配置 DTO
- ComplianceFinding 读取 DTO

W20-T0b 起补充 P3 W17/W18 配套的只读 DTO：
- VoicePackRead：音色包列表/详情视图
- SubtitleStyleRead：字幕样式列表/详情视图

跨层契约（输入/输出 DTO、供应商配置等）统一沉淀在 ``app/core/contracts``，
此处仅承载与 commerce HTTP 接口直接相关的 Pydantic 模型，避免与任务层耦合。
"""

from app.schemas.commerce.outcome import (
    StoryOutcomeCreate,
    StoryOutcomeRead,
    StoryOutcomeUpdate,
)
from app.schemas.commerce.product import (
    ProductCreate,
    ProductImageCreate,
    ProductImageRead,
    ProductRead,
    ProductUpdate,
)
from app.schemas.commerce.product_image_generation import (
    ProductImageGenerationRequest,
    ProductImageGenerationResponse,
)
from app.schemas.commerce.subtitle_styles import SubtitleStyleRead
from app.schemas.commerce.voice_packs import VoicePackRead

__all__ = [
    "ProductCreate",
    "ProductImageCreate",
    "ProductImageGenerationRequest",
    "ProductImageGenerationResponse",
    "ProductImageRead",
    "ProductRead",
    "ProductUpdate",
    "StoryOutcomeCreate",
    "StoryOutcomeRead",
    "StoryOutcomeUpdate",
    "SubtitleStyleRead",
    "VoicePackRead",
]
