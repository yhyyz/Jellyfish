"""字幕样式 + 字幕轨道模型（P3 W18 引入）。

包含两张表：

- subtitle_styles：跨项目复用的字幕样式定义（DOUYIN_DEFAULT / TIKTOK_VIRAL /
  REELS_LOWER_THIRD 三套系统级内置 + 项目级覆盖）；启动期由
  builtin_subtitle_styles 幂等 seed 系统级样式（is_system=True，
  project_id=NULL）；项目级覆盖样式由 ``POST /api/v1/commerce/projects/
  {project_id}/subtitle-styles`` 在 P5 W30 上线（is_system=False，
  project_id 非空）。
- subtitle_tracks：单镜头/单章节级别的字幕轨道实例，挂在 ``shot_id``，
  关联具体的 ``.ass`` 文件 FileItem 与所用 SubtitleStyle，记录字级时间戳
  来源（来自 TTS word_timestamps 还是 ASR Paraformer-v2 反推）。

字段语义遵循 ASS v4+ Style 行规范（[V4+ Styles] Format 字段顺序），
仅做语义化命名转换。颜色字段统一以 ``&HAABBGGRR`` 字符串形式存储，
渲染时直接拼到 .ass 文件不需二次转换。
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import (
    SubtitleAlignment,
    SubtitleFormat,
    SubtitleSource,
)


class SubtitleStyle(Base, TimestampMixin):
    """字幕样式：跨项目复用的 ASS Style 定义。

    系统级样式（is_system=True，project_id=NULL）由启动期
    builtin_subtitle_styles 幂等 seed（DOUYIN_DEFAULT / TIKTOK_VIRAL /
    REELS_LOWER_THIRD 三套）；项目级覆盖样式（is_system=False，
    project_id=具体 project ID）由前端 SubtitleStyleEditor 通过
    ``POST /api/v1/commerce/projects/{project_id}/subtitle-styles`` 创建。
    渲染期 ``shot_subtitle_render_worker`` 通过
    :func:`subtitle_style_service.resolve_for_shot` 走"项目级 → 系统级
    fallback"两级 lookup。

    字段语义对应 ASS v4+ ``[V4+ Styles] Format`` 行：

    - ``font_family`` ↔ Fontname；``font_size`` ↔ Fontsize（脚本像素，按
      ``play_res_y=1920`` 计）；
    - ``primary_colour`` / ``secondary_colour`` / ``outline_colour`` /
      ``back_colour`` ↔ ASS 同名字段，统一 ``&HAABBGGRR`` 字符串；
    - ``bold`` / ``italic`` / ``border_style`` / ``outline`` / ``shadow`` /
      ``alignment`` / ``margin_l`` / ``margin_r`` / ``margin_v`` ↔ ASS 同名字段；
    - ``font_fallback_chain`` JSON list[str]：libass 无 CSS 风格 fallback，但
      jellyfish 服务侧渲染前可按系统已安装字体逐项探测，缺失则下移；中英
      混合场景常用 ``["Source Han Sans CN Heavy", "PingFang SC", "Arial"]``。
    """

    __tablename__ = "subtitle_styles"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="字幕样式 ID（如 douyin_default / tiktok_viral / reels_lower_third）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="展示名称（如 抖音默认 / TikTok 病毒式）",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="样式描述（适用平台、视觉特点等）",
    )
    language_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh-CN",
        server_default="zh-CN",
        index=True,
        comment="主语言代码（决定 font_fallback_chain 默认值与 ASS Encoding）",
    )
    format: Mapped[SubtitleFormat] = mapped_column(
        String(8),
        nullable=False,
        default=SubtitleFormat.ass.value,
        server_default=SubtitleFormat.ass.value,
        index=True,
        comment="字幕文件格式：ass / srt / vtt",
    )
    font_family: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="主字体 family name（ASS Fontname；缺失时由 font_fallback_chain 兜底）",
    )
    font_fallback_chain: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="字体回退链 list[str]（渲染前按系统字体逐项探测，找不到时下移）",
    )
    font_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="字号（脚本像素，按 PlayResY=1920 计）",
    )
    primary_colour: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="&H00FFFFFF",
        server_default="&H00FFFFFF",
        comment="主填充色 &HAABBGGRR（高亮后 / \\kf 终态色）",
    )
    secondary_colour: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="&H00FFFFFF",
        server_default="&H00FFFFFF",
        comment="预高亮色 &HAABBGGRR（\\kf 起始色，无逐词高亮时与 primary 一致）",
    )
    outline_colour: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="&H00000000",
        server_default="&H00000000",
        comment="描边色 &HAABBGGRR（BorderStyle=1）或盒背景色（=3）",
    )
    back_colour: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="&H80000000",
        server_default="&H80000000",
        comment="阴影色 &HAABBGGRR（透明度通过 alpha 字节控制）",
    )
    bold: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="是否粗体（移动端可读性默认开启）",
    )
    italic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="是否斜体",
    )
    border_style: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒",
    )
    outline: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=3.0,
        server_default="3.0",
        comment="描边宽度（像素）",
    )
    shadow: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
        comment="阴影偏移（像素）",
    )
    alignment: Mapped[SubtitleAlignment] = mapped_column(
        String(16),
        nullable=False,
        default=SubtitleAlignment.bottom_center.value,
        server_default=SubtitleAlignment.bottom_center.value,
        comment="ASS Alignment：底/中/上 × 左/中/右 numpad 1-9 布局的语义化映射",
    )
    margin_l: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="左边距（像素）",
    )
    margin_r: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="右边距（像素）",
    )
    margin_v: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=200,
        server_default="200",
        comment="垂直边距（像素）：alignment 为 bottom_* 时离底部，top_* 时离顶部",
    )
    play_res_x: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1080,
        server_default="1080",
        comment="ASS PlayResX：脚本坐标系宽度，应等于视频原生宽（1080）",
    )
    play_res_y: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1920,
        server_default="1920",
        comment="ASS PlayResY：脚本坐标系高度，应等于视频原生高（1920）",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="系统级样式标记，true 时不可被用户删除",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="UI 列表显示顺序（升序）",
    )
    project_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment=(
            "项目级覆盖样式归属的项目 ID；NULL=系统级 seed，"
            "非 NULL=该项目自定义覆盖；删除项目时随同 CASCADE"
        ),
    )

    __table_args__ = (
        Index("ix_subtitle_styles_format_lang", "format", "language_code"),
    )


class SubtitleTrack(Base, TimestampMixin):
    """字幕轨道：单镜头级别的字幕实例。

    一个 ``Shot`` 可关联多条 SubtitleTrack（如同时存在中文 ASS + 英文 SRT
    多语言版本），但通常生产链路下每个镜头每种语言保留 1 条最新版本。

    ``source`` 字段记录字级时间戳来源，与 W17 收尾的 ``audio_strategy``
    双路径产出严格对应：``silent_with_tts`` → ``tts_word_timestamps``，
    ``keep_native`` → ``asr_paraformer_v2``。
    """

    __tablename__ = "subtitle_tracks"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="字幕轨道 ID（uuid4().hex）",
    )
    shot_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("shots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属镜头 ID",
    )
    style_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("subtitle_styles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="使用的 SubtitleStyle ID；删除样式时 SET NULL，已渲染产物保留",
    )
    file_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="渲染产物 FileItem ID（.ass / .srt / .vtt 文件落 minio）",
    )
    language_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh-CN",
        server_default="zh-CN",
        index=True,
        comment="字幕语言代码",
    )
    format: Mapped[SubtitleFormat] = mapped_column(
        String(8),
        nullable=False,
        default=SubtitleFormat.ass.value,
        server_default=SubtitleFormat.ass.value,
        comment="字幕文件格式（与 file_id 内容一致）",
    )
    source: Mapped[SubtitleSource] = mapped_column(
        String(32),
        nullable=False,
        default=SubtitleSource.tts_word_timestamps.value,
        server_default=SubtitleSource.tts_word_timestamps.value,
        index=True,
        comment="字级时间戳来源：tts_word_timestamps / asr_paraformer_v2 / manual",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="字幕末尾时间戳（即覆盖音频时长，0 表示空轨）",
    )

    __table_args__ = (
        Index("ix_subtitle_tracks_shot_lang", "shot_id", "language_code"),
    )


__all__ = ["SubtitleStyle", "SubtitleTrack"]
