"""字幕样式只读响应 schemas（W20-T0b，P3 W18 配套）。

本模块对应 :class:`app.models.subtitle.SubtitleStyle`，仅暴露列表读取
所需的 DTO，不提供 Create/Update/Delete：

- 系统级样式（``is_system=True``）由
  :func:`app.services.studio.builtin_subtitle_styles.bootstrap_builtin_subtitle_styles`
  在启动期幂等 seed（DOUYIN_DEFAULT / TIKTOK_VIRAL / REELS_LOWER_THIRD
  三套），应用层接口不允许新增/编辑/删除；
- 项目级覆盖样式的写入路径将在后续 wave 由专门的项目设置面板暴露，
  本模块同样只读。

字段语义遵循 ASS v4+ Style 行规范（``[V4+ Styles] Format`` 字段顺序），
仅做语义化命名转换。``alignment`` 在 ORM 中以语义化字符串枚举（``bottom_center``
等）存储，本 schema 暴露为 ASS numpad int（1-9），便于前端预览组件直接
匹配 ASS 渲染坐标系（参见
:class:`app.models.types.SubtitleAlignment` 注释中的 numpad 映射）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubtitleStyleRead(BaseModel):
    """SubtitleStyle 只读响应。

    用于 ``GET /api/v1/commerce/subtitle-styles`` 列表接口。字段直接映射
    自 ORM 列；``alignment`` 字段由 service 层从 ``SubtitleAlignment`` 字
    符串枚举换算为 ASS numpad int（1-9）后注入，因此本 schema 不开
    ``from_attributes`` —— 路由层用 ``model_validate(dict)`` 走 dict 路径
    保证类型一致。
    """

    model_config = ConfigDict(from_attributes=False)

    id: str = Field(
        ...,
        description="字幕样式 ID（如 douyin_default / tiktok_viral / reels_lower_third）",
    )
    name: str = Field(..., description="展示名称（如 抖音默认 / TikTok 病毒式）")
    description: str | None = Field(
        None,
        description="样式描述（适用平台、视觉特点等）",
    )
    language_code: str = Field(
        ...,
        description="主语言代码（决定 font_fallback_chain 默认值与 ASS Encoding）",
    )
    format: str = Field(
        ...,
        description="字幕文件格式：ass / srt / vtt",
    )
    font_family: str = Field(
        ...,
        description="主字体 family name（ASS Fontname；缺失时由 font_fallback_chain 兜底）",
    )
    font_size: int = Field(
        ...,
        description="字号（脚本像素，按 PlayResY=1920 计）",
    )
    primary_colour: str = Field(
        ...,
        description="主填充色 &HAABBGGRR（高亮后 / \\kf 终态色）",
    )
    secondary_colour: str | None = Field(
        None,
        description="预高亮色 &HAABBGGRR（\\kf 起始色，无逐词高亮时与 primary 一致）",
    )
    outline_colour: str = Field(
        ...,
        description="描边色 &HAABBGGRR（BorderStyle=1）或盒背景色（=3）",
    )
    back_colour: str | None = Field(
        None,
        description="阴影色 &HAABBGGRR（透明度通过 alpha 字节控制）",
    )
    bold: bool = Field(..., description="是否粗体（移动端可读性默认开启）")
    italic: bool = Field(..., description="是否斜体")
    border_style: int = Field(
        ...,
        description="ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒",
    )
    outline: float = Field(..., description="描边宽度（像素）")
    shadow: float = Field(..., description="阴影偏移（像素）")
    alignment: int = Field(
        ...,
        description="ASS Alignment numpad（1-9）：1=底左 / 2=底中 / 3=底右 / 4=中左 / 5=中中 / 6=中右 / 7=顶左 / 8=顶中 / 9=顶右",
        ge=1,
        le=9,
    )
    margin_l: int = Field(..., description="左边距（像素）")
    margin_r: int = Field(..., description="右边距（像素）")
    margin_v: int = Field(
        ...,
        description="垂直边距（像素）：alignment 为 bottom_* 时离底部，top_* 时离顶部",
    )
    play_res_x: int = Field(
        ...,
        description="ASS PlayResX：脚本坐标系宽度，应等于视频原生宽（1080）",
    )
    play_res_y: int = Field(
        ...,
        description="ASS PlayResY：脚本坐标系高度，应等于视频原生高（1920）",
    )
    font_fallback_chain: list[str] | None = Field(
        None,
        description="字体回退链 list[str]（渲染前按系统字体逐项探测，找不到时下移）",
    )
    is_system: bool = Field(
        ...,
        description="系统级样式标记，true 时不可被用户删除",
    )
    sort_order: int = Field(..., description="UI 列表显示顺序（升序）")
    created_at: datetime = Field(..., description="入库时间")
    updated_at: datetime = Field(..., description="最近一次更新时间")


__all__ = ["SubtitleStyleRead"]
