"""音色包只读响应 schemas（W20-T0b，P3 W17 配套）。

本模块对应 :class:`app.models.voice_pack.VoicePack`，仅暴露列表/详情读取
所需的 DTO，不提供 Create/Update/Delete：

- 系统级音色包（``is_system=True``）由
  :func:`app.services.studio.builtin_voice_packs.bootstrap_builtin_voice_packs`
  在启动期幂等 seed，应用层接口不允许新增/编辑/删除；
- 用户自定义音色（``is_system=False``）的写入路径在 W20+ 由专门的语
  音克隆流程独立暴露，本模块同样只读。

只读语义：
    - 字段直接映射自 ORM 列，便于前端音色选择器（VoicePackPicker）与
      ``/commerce/voice-packs`` 列表页直接消费；
    - ``model_config = ConfigDict(from_attributes=True)`` 让路由层可以
      ``VoicePackRead.model_validate(orm_row)`` 一键序列化，无需 service
      手工 to_dict。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VoicePackRead(BaseModel):
    """VoicePack 只读响应。

    用于 ``GET /api/v1/commerce/voice-packs`` 列表接口。字段直接映射自
    ORM 列；Enum 列（``provider`` / ``gender``）在 ORM 层已是 ``str``
    化的枚举值，pydantic 直接读取即可。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="音色包 ID（如 cosyvoice_v2_longxiaochun）")
    name: str = Field(..., description="展示名称（如 龙小淳）")
    provider: str = Field(
        ...,
        description="TTS 供应商（aliyun_cosyvoice / openai_tts）",
    )
    provider_voice_id: str = Field(
        ...,
        description="供应商侧音色 ID（如 longxiaochun_v2）",
    )
    language_code: str = Field(
        ...,
        description="语言代码（zh-CN / en-US / ja-JP 等）",
    )
    gender: str | None = Field(
        None,
        description="声纹性别（male / female / neutral / child）",
    )
    archetype_hint: str | None = Field(
        None,
        description="与 BrandArchetype 的语义匹配提示（如 sage / elder）",
    )
    sample_file_id: str | None = Field(
        None,
        description="试听样本音频 file_id；自定义克隆音色为训练样本",
    )
    description: str | None = Field(
        None,
        description="音色描述（适用场景、特质等）",
    )
    default_speed: float = Field(
        ...,
        description="默认语速（0.5-2.0），TTS 估时长用",
    )
    is_system: bool = Field(..., description="系统级音色标记，true 时不可被用户删除")
    sort_order: int = Field(..., description="UI 列表显示顺序（升序）")
    created_at: datetime = Field(..., description="入库时间")
    updated_at: datetime = Field(..., description="最近一次更新时间")


__all__ = ["VoicePackRead"]
