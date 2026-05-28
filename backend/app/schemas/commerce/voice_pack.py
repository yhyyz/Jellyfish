"""自定义音色训练 API 边界 schema（P5 W29 引入）。

为什么单独拆 ``voice_pack.py`` 而不并入 ``voice_packs.py``：
    ``voice_packs.py`` 是 P3 W17 落地的 **只读** 列表 schema（VoicePackRead）；
    P5 W29 的自定义音色训练 endpoint 需要独立的 Create / Status / List item
    DTO，承载 W29 才出现的 ``clone_status`` / ``target_model`` / ``region`` /
    ``cloned_at`` 等字段。把这部分单独成文件让 W17 只读 schema 保持稳定，避
    免改动 P3 历史接口。

按 AGENTS.md §4 严格分层：本模块只定义 HTTP 边界 schema，业务 DTO 仍在
:mod:`app.core.contracts.voice_pack_contracts`，前者不向后者引用 ORM。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomVoiceListItem(BaseModel):
    """自定义音色列表单项 DTO。

    用于 ``GET /api/v1/commerce/voice-packs/custom?clone_status=&limit=&offset=``
    分页结果中的每条记录；前端 VoicePackLibrary 列表 + clone_status badge
    直接消费。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="VoicePack 行主键（clone_xxx 形式）")
    name: str = Field(..., description="用户自定义展示名")
    provider: str = Field(..., description="TTS 供应商；自定义音色固定为 aliyun_cosyvoice")
    provider_voice_id: str = Field(..., description="DashScope 返回的 voice_id")
    language_code: str = Field(..., description="语言代码（zh-CN / en-US 等）")
    gender: str | None = Field(None, description="声纹性别（一般 neutral）")
    archetype_hint: str | None = Field(None, description="可选 BrandArchetype 提示")
    description: str | None = Field(None, description="用户自定义描述")
    target_model: str | None = Field(
        None, description="DashScope 目标合成模型（cosyvoice-v3.5-plus 等）"
    )
    region: str | None = Field(None, description="DashScope 区域端点")
    clone_status: str | None = Field(
        None,
        description="voice clone 状态：deploying / ready / failed / deleted",
    )
    cloned_at: datetime | None = Field(
        None, description="ready 时的完成时间戳；其他状态为 NULL"
    )
    is_system: bool = Field(..., description="系统级音色标记；自定义音色恒为 false")
    sort_order: int = Field(..., description="UI 列表显示顺序")
    created_at: datetime = Field(..., description="入库时间")
    updated_at: datetime = Field(..., description="最近一次更新时间")


__all__ = ["CustomVoiceListItem"]
