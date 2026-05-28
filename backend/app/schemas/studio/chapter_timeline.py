"""章节视频时间线读写与导出相关 Schema（与 OpenAPI 契约对齐）。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

_PREVIEW_NOTE_DEFAULT = (
    "剪辑页支持顺序预览与入出点裁剪；导出将按裁剪拼接成片。"
)


class TimelineClipStatus(str, Enum):
    """片段成片解析状态（展示用）。"""

    ready = "ready"
    missing_video = "missing_video"
    file_missing = "file_missing"


class ChapterTimelineSegmentWrite(BaseModel):
    """保存时间线时的一段（顺序由数组顺序表达）。"""

    shot_id: str = Field(..., description="镜头 ID")
    trim_start_ms: int | None = Field(
        None,
        ge=0,
        description="裁剪入点毫秒（可选）；与 trim_end_ms 均为空表示全长；否则区间为左闭右开 [start,end)",
    )
    trim_end_ms: int | None = Field(
        None,
        ge=0,
        description="裁剪出点毫秒（exclusive，可选）；为空则默认为源成片时长",
    )
    subtitle_track_file_id: str | None = Field(
        None,
        description=(
            "P3 W19：本段渲染好的 .ass 字幕 FileItem ID（W18 shot_subtitle_render"
            "_worker 产出），合成阶段 ffmpeg subtitles= 滤镜硬烧到画面"
        ),
    )
    tts_audio_file_id: str | None = Field(
        None,
        description=(
            "P3 W19：本段 TTS 合成音频 FileItem ID；audio_strategy=silent_with_tts "
            "时合成阶段 amix 混入"
        ),
    )
    bgm_file_id: str | None = Field(
        None,
        description=(
            "P5 W31：本段 BGM 音轨 FileItem ID（usage_kind=bgm_track）。"
            "AudioMixMode in {voice_bgm, full} 时合成阶段混入；voice_only 忽略；"
            "为空时 voice_bgm/full 自动 fallback 到 voice_only"
        ),
    )
    sfx_file_id: str | None = Field(
        None,
        description=(
            "P5 W31：本段 SFX 音轨 FileItem ID（usage_kind=sfx_track）。"
            "仅 AudioMixMode=full 合成阶段通过 amerge 加入；为空时 full 自动"
            "降级为带 ducking 的 voice_bgm"
        ),
    )
    bgm_ducking_db: float = Field(
        default=-12.0,
        ge=-30.0,
        le=0.0,
        description=(
            "P5 W31：full 模式 sidechaincompress 自动 ducking 增益（dB），"
            "范围 [-30.0, 0.0]，默认 -12.0；voice_bgm 用静态 weights 不读此字段"
        ),
    )


class ChapterTimelineWrite(BaseModel):
    """全量替换章节时间线片段。"""

    layout_version: int | None = Field(None, description="与 GET 返回一致时可校验乐观锁")
    segments: list[ChapterTimelineSegmentWrite] = Field(default_factory=list)


class ChapterTimelineSegmentRead(BaseModel):
    """时间线片段读取模型（含成片文件解析状态）。"""

    id: str = Field(..., description="片段行 ID；尚未落库的合成行可为空字符串")
    shot_id: str
    position: int = Field(..., ge=0)
    trim_start_ms: int | None = Field(None, description="已保存入点毫秒；null 表示从 0")
    trim_end_ms: int | None = Field(None, description="已保存出点毫秒（exclusive）；null 表示至片尾")
    subtitle_track_file_id: str | None = Field(
        None,
        description="P3 W19：本段字幕 .ass 文件 FileItem ID（chapter_av_export 烧录用）",
    )
    tts_audio_file_id: str | None = Field(
        None,
        description="P3 W19：本段 TTS 音频 FileItem ID（silent_with_tts 路径混入）",
    )
    bgm_file_id: str | None = Field(
        None,
        description="P5 W31：本段 BGM FileItem ID（voice_bgm/full 模式混入）",
    )
    sfx_file_id: str | None = Field(
        None,
        description="P5 W31：本段 SFX FileItem ID（仅 full 模式 amerge 加入）",
    )
    bgm_ducking_db: float = Field(
        default=-12.0,
        ge=-30.0,
        le=0.0,
        description="P5 W31：full 模式 sidechaincompress ducking 增益（dB）",
    )
    clip_status: TimelineClipStatus
    file_id: str | None = None
    label: str = Field("", description="镜头标题等展示字段")


class ChapterTimelineRead(BaseModel):
    """章节时间线读取模型。"""

    layout_version: int = Field(1, ge=1)
    segments: list[ChapterTimelineSegmentRead] = Field(default_factory=list)
    preview_note: str = Field(default=_PREVIEW_NOTE_DEFAULT, description="连续预览能力说明")


class ChapterTimelineEncodeMode(str, Enum):
    """导出编码策略。"""

    uniform_transcode = "uniform_transcode"
    lossless_concat_only = "lossless_concat_only"


class ChapterTimelineExportRequest(BaseModel):
    """发起章节时间线导出任务。"""

    idempotency_key: str | None = Field(None, description="可选幂等键")
    encode_mode: ChapterTimelineEncodeMode = Field(
        default=ChapterTimelineEncodeMode.uniform_transcode,
        description="uniform_transcode：统一转码拼接；lossless_concat_only：仅当片段编码一致时无损拼接",
    )


class ChapterTimelineSegmentAudioPatch(BaseModel):
    """P5 W31-T8：单 segment BGM/SFX/ducking 偏量更新入参。

    与 ``ChapterTimelineWrite`` 全量替换语义区分：本 DTO 仅承载 audio
    相关三字段且全部可选，``None`` 表示"显式清空（写 NULL）"，字段缺省
    表示"保持当前值不变"。校验范围与 ORM/0020 alembic 列约束一致。

    Pydantic 怎么区分"未传"与"显式 null"：路由层通过
    ``model_dump(exclude_unset=True)`` 拿到只含被传入字段的 dict；任何
    未在请求体里出现的字段都不会进入 dict，从而保留 segment 已有值。
    """

    bgm_file_id: str | None = Field(
        default=None,
        description="本段 BGM FileItem ID；显式传 null 即清空当前 BGM 关联",
    )
    sfx_file_id: str | None = Field(
        default=None,
        description="本段 SFX FileItem ID；显式传 null 即清空当前 SFX 关联",
    )
    bgm_ducking_db: float | None = Field(
        default=None,
        ge=-30.0,
        le=0.0,
        description=(
            "full 模式 sidechaincompress ducking 增益（dB），范围 "
            "[-30.0, 0.0]；不传则保持原值"
        ),
    )
