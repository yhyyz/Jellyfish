"""字幕样式只读响应 schemas（W20-T0b，P3 W18 配套）+ 项目级 CRUD（W30-T3）。

本模块对应 :class:`app.models.subtitle.SubtitleStyle`：

- :class:`SubtitleStyleRead`：只读列表/详情 DTO，供 ``GET`` 路径与
  W30 ``GET /commerce/projects/{project_id}/subtitle-styles`` merged 视图
  共用。
- :class:`ProjectSubtitleStyleCreateInput` / :class:`ProjectSubtitleStyleUpdateInput`：
  W30 项目级 CRUD 写入 DTO，仅暴露用户可编辑字段，不接受 ``id`` /
  ``project_id`` / ``is_system`` / ``sort_order`` / ``created_at`` /
  ``updated_at`` 等服务端管理字段。

字段语义遵循 ASS v4+ Style 行规范（``[V4+ Styles] Format`` 字段顺序），
仅做语义化命名转换。``alignment`` 在 ORM 中以语义化字符串枚举（``bottom_center``
等）存储，本模块对外暴露为 ASS numpad int（1-9），便于前端预览组件直接
匹配 ASS 渲染坐标系（参见
:class:`app.models.types.SubtitleAlignment` 注释中的 numpad 映射）。

写入路径设计：
    - 系统级行（``project_id IS NULL``）只读，POST/PATCH/DELETE 一律 403；
      系统级 seed 由
      :func:`app.services.studio.builtin_subtitle_styles.bootstrap_builtin_subtitle_styles`
      在启动期幂等管理。
    - 项目级覆盖（``project_id`` 非空）走 W30 新引入的 CRUD；同 project
      内 ``name`` 唯一（service 层 enforce），跨 project 允许重名。
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
    project_id: str | None = Field(
        None,
        description="项目级覆盖归属的项目 ID；NULL=系统级 seed，非 NULL=该项目自定义",
    )
    created_at: datetime = Field(..., description="入库时间")
    updated_at: datetime = Field(..., description="最近一次更新时间")


class ProjectSubtitleStyleCreateInput(BaseModel):
    """项目级 SubtitleStyle 写入 DTO（W30-T3 POST 入参）。

    仅暴露用户可编辑字段；``id`` / ``project_id`` / ``is_system`` /
    ``sort_order`` / ``created_at`` / ``updated_at`` 等服务端管理字段
    在 service 层注入，不允许调用方传入。

    校验由 service 层做 ``(project_id, name)`` 唯一性 enforce；schema
    层只做基础形态约束（必填、长度、numeric 范围）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="展示名称")
    description: str | None = Field(
        None, max_length=2048, description="样式描述（适用平台、视觉特点等）"
    )
    language_code: str = Field(
        "zh-CN", min_length=2, max_length=16, description="主语言代码"
    )
    format: str = Field(
        "ass",
        description="字幕文件格式：ass / srt / vtt",
        pattern=r"^(ass|srt|vtt)$",
    )
    font_family: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="主字体 family name（ASS Fontname）",
    )
    font_size: int = Field(..., ge=16, le=200, description="字号（脚本像素）")
    primary_colour: str = Field(
        "&H00FFFFFF",
        description="主填充色 &HAABBGGRR",
        pattern=r"^&H[0-9A-Fa-f]{8}$",
    )
    secondary_colour: str = Field(
        "&H00FFFFFF",
        description="预高亮色 &HAABBGGRR",
        pattern=r"^&H[0-9A-Fa-f]{8}$",
    )
    outline_colour: str = Field(
        "&H00000000",
        description="描边色 &HAABBGGRR",
        pattern=r"^&H[0-9A-Fa-f]{8}$",
    )
    back_colour: str = Field(
        "&H80000000",
        description="阴影色 &HAABBGGRR",
        pattern=r"^&H[0-9A-Fa-f]{8}$",
    )
    bold: bool = Field(True, description="是否粗体")
    italic: bool = Field(False, description="是否斜体")
    border_style: int = Field(
        1, ge=1, le=3, description="ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒"
    )
    outline: float = Field(3.0, ge=0.0, le=20.0, description="描边宽度（像素）")
    shadow: float = Field(1.0, ge=0.0, le=20.0, description="阴影偏移（像素）")
    alignment: int = Field(
        2,
        ge=1,
        le=9,
        description=(
            "ASS Alignment numpad（1-9）：1=底左 / 2=底中 / 3=底右 / "
            "4=中左 / 5=中中 / 6=中右 / 7=顶左 / 8=顶中 / 9=顶右"
        ),
    )
    margin_l: int = Field(60, ge=0, le=2000, description="左边距（像素）")
    margin_r: int = Field(60, ge=0, le=2000, description="右边距（像素）")
    margin_v: int = Field(200, ge=0, le=2000, description="垂直边距（像素）")
    play_res_x: int = Field(1080, ge=64, le=8192, description="ASS PlayResX")
    play_res_y: int = Field(1920, ge=64, le=8192, description="ASS PlayResY")
    font_fallback_chain: list[str] | None = Field(
        None, description="字体回退链 list[str]"
    )


class ProjectSubtitleStyleUpdateInput(BaseModel):
    """项目级 SubtitleStyle 更新 DTO（W30-T3 PATCH 入参）。

    所有字段均 optional，service 层只更新 explicit 提供的字段（``model_dump
    (exclude_unset=True)``）；不允许把项目级行的 ``project_id`` / ``id`` /
    ``is_system`` 改写。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2048)
    language_code: str | None = Field(None, min_length=2, max_length=16)
    format: str | None = Field(None, pattern=r"^(ass|srt|vtt)$")
    font_family: str | None = Field(None, min_length=1, max_length=128)
    font_size: int | None = Field(None, ge=16, le=200)
    primary_colour: str | None = Field(None, pattern=r"^&H[0-9A-Fa-f]{8}$")
    secondary_colour: str | None = Field(None, pattern=r"^&H[0-9A-Fa-f]{8}$")
    outline_colour: str | None = Field(None, pattern=r"^&H[0-9A-Fa-f]{8}$")
    back_colour: str | None = Field(None, pattern=r"^&H[0-9A-Fa-f]{8}$")
    bold: bool | None = None
    italic: bool | None = None
    border_style: int | None = Field(None, ge=1, le=3)
    outline: float | None = Field(None, ge=0.0, le=20.0)
    shadow: float | None = Field(None, ge=0.0, le=20.0)
    alignment: int | None = Field(None, ge=1, le=9)
    margin_l: int | None = Field(None, ge=0, le=2000)
    margin_r: int | None = Field(None, ge=0, le=2000)
    margin_v: int | None = Field(None, ge=0, le=2000)
    play_res_x: int | None = Field(None, ge=64, le=8192)
    play_res_y: int | None = Field(None, ge=64, le=8192)
    font_fallback_chain: list[str] | None = None


__all__ = [
    "ProjectSubtitleStyleCreateInput",
    "ProjectSubtitleStyleUpdateInput",
    "SubtitleStyleRead",
]
