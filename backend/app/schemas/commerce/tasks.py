"""commerce/* 异步任务入口的请求/响应 schema（W6-T3）。

设计要点
--------

本模块只承载 3 个 ``commerce/*`` POST 接口（商品信息抽取 / 剧情脚本生成 /
合规检查）的 HTTP 请求体，以及它们共享的统一 ``TaskEnqueueResponse``
响应壳；任何与具体 worker 实现（agent 实例化、LLM 选择、CTA 模板等）
相关的字段都不应出现在这里——那些是 service 层与 worker 层的内部协议。

为什么所有请求 schema 都启用 ``extra="forbid"``：
    commerce/* 入口直接面向前端发起的“一锤子”任务请求，错填字段在
    线下被静默吞掉的成本极高（已经写库 + 已经投递 Celery）。所以这里
    全部走严格模式，让前端在联调期就能拿到 422 的明确反馈。

为什么 ``ScriptGenerateRequest.target_duration_sec`` 用 ``Field(ge=15, le=180)``：
    与剧情带货短视频的实际投放窗口对齐——抖音/快手/视频号的“剧情带货”
    视频普遍落在 15–180 秒之间。低于 15 秒无法承载剧情转折，高于 180
    秒既不利于完播也容易触发平台的二级合规策略。在 schema 层硬卡可以
    避免无意义的 worker 调用产生成本（Token / 配额）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductExtractRequest(BaseModel):
    """``POST /api/v1/commerce/products/extract`` 请求体。

    Attributes:
        raw_text: 商品原始文本来源（详情页拷贝、口述描述、SEO 标题等），
            由 worker 层做长度截断与归一化，schema 层只保证字段存在。
        target_fields: 期望提取的字段白名单；``None`` 表示按 worker 默认
            策略提取全部可识别字段，传空列表与 ``None`` 同义。
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(..., min_length=1, description="商品原始文本（详情页 / 描述 / 链接抓取后的纯文本）")
    target_fields: list[str] | None = Field(
        default=None,
        description="期望提取的字段白名单；不传或传 null 表示提取全部可识别字段",
    )


class ScriptGenerateRequest(BaseModel):
    """``POST /api/v1/commerce/script-generate`` 请求体。

    剧情脚本生成的输入比商品抽取复杂：除了项目/章节锚点外，还包含商品快照、
    受众画像、原型、调性栅格、目标时长、投放平台等参数。这些字段不再走
    ``extra=allow``，目的是在前后端联调期就能识别出过期 / 拼写错误的字段。

    Attributes:
        project_id: 所属项目 ID。
        chapter_id: 所属章节 ID（剧情带货项目仍按章节组织剧本）。
        formula_id: 选用的故事公式 ID（来自 ``story_formulas``）。
        product: 商品快照 JSON（worker 在执行时不再回查 DB，确保历史可追溯）。
        audience: 受众画像 JSON（年龄层 / 性别 / 兴趣标签等）。
        archetype: 角色原型，默认 ``Sage``，与 ``StoryScriptGeneratorAgent`` 对齐。
        tone_grid: 调性栅格（认真/幽默、专业/接地气等坐标）。
        target_duration_sec: 目标视频时长（秒），15 ≤ x ≤ 180。
        platform: 目标投放平台，默认 ``douyin``，由 worker 决定地域/口径。
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, description="所属项目 ID")
    chapter_id: str = Field(..., min_length=1, description="所属章节 ID")
    formula_id: str = Field(..., min_length=1, description="使用的故事公式 ID")
    product: dict[str, Any] = Field(..., description="商品快照 JSON")
    audience: dict[str, Any] = Field(..., description="受众画像 JSON")
    archetype: str = Field(default="Sage", description="叙事原型，默认 Sage")
    tone_grid: dict[str, Any] = Field(default_factory=dict, description="调性栅格 JSON")
    target_duration_sec: int = Field(
        ...,
        ge=15,
        le=180,
        description="目标视频时长（秒），约束在 15–180 之间",
    )
    platform: str = Field(default="douyin", description="目标投放平台，默认 douyin")


class ComplianceCheckRequest(BaseModel):
    """``POST /api/v1/commerce/compliance/check`` 请求体。

    合规检查要么针对“某个具体变体的当前剧本”，要么针对“调用方手里
    临时拼出的脚本片段”。``script_text`` 留为可选字段：worker 在 None
    时会按 ``variant_id`` 回查最新剧本；非空时直接使用该字符串，避免
    一些“想看看新文案是否合规”的轻量调试场景被强制要求改写到 DB。

    Attributes:
        variant_id: 变体 ID，作为 ``ComplianceFinding.variant_id`` 外键。
        region: 适用合规地域（与 ``ComplianceProfile.region`` 对齐）。
        product_category: 商品品类，影响是否触发健康/食品等专项规则。
        script_text: 待校验的脚本文本；为 ``None`` 时 worker 回查变体当前剧本。
        script_duration_sec: 脚本对应的视频时长（秒），用于判定品牌口播频次。
        brand_aliases: 品牌别名（含商品名/品类俚语），影响品牌频次规则命中。
    """

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(..., min_length=1, description="所属变体 ID")
    region: str = Field(default="cn_mainland", description="合规地域，默认 cn_mainland")
    product_category: str = Field(default="other", description="商品品类，默认 other")
    script_text: str | None = Field(
        default=None,
        description="待校验脚本文本；为空时 worker 回查变体当前剧本",
    )
    script_duration_sec: int = Field(default=60, ge=1, description="脚本对应视频时长（秒）")
    brand_aliases: list[str] = Field(default_factory=list, description="品牌别名列表（含商品名/俚语）")


class ChapterAvPlanRequest(BaseModel):
    """``POST /api/v1/commerce/chapter-av-plan`` 请求体（P3 W17）。

    触发 ``chapter_av_plan`` worker：对章节内所有 ``ShotDialogLine`` 跑
    Decision F 决策树（estimate → speed_adjust → llm_rewrite → hold），
    keep_native shot 跳过整树。
    """

    model_config = ConfigDict(extra="forbid")

    chapter_id: str = Field(..., min_length=1, description="目标章节 ID")


class TtsGenerateRequest(BaseModel):
    """``POST /api/v1/commerce/tts/generate`` 请求体（P3 W17）。

    触发 ``tts_generate`` worker：用 CosyVoice 合成单段对白音频，落
    FileItem + tts_cache。``cache_key = sha256(text|voice_pack_id|speed:.3f)``
    命中即直接复用既有音频。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="待合成文本")
    voice_pack_id: str = Field(..., min_length=1, description="VoicePack 主键（如 cosyvoice_v2_longxiaochun）")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速倍率，0.5–2.0")
    audio_format: str = Field(default="mp3", description="输出格式：mp3 / wav / pcm / opus")
    enable_word_timestamps: bool = Field(default=True, description="是否启用字级时间戳")


class AsrSubtitleGenerateRequest(BaseModel):
    """``POST /api/v1/commerce/asr-subtitle-generate`` 请求体（P3 W17 收尾）。

    触发 ``asr_subtitle_generate`` worker：用 Paraformer-v2 反推视频/音频
    自带音轨的字级时间戳，供 keep_native 路径生成字幕。要求
    ``video_file_id`` 对应的 FileItem 公网可访问（DashScope 限制）。
    """

    model_config = ConfigDict(extra="forbid")

    video_file_id: str = Field(..., min_length=1, description="源视频 / 音频 FileItem ID")
    language_hints: list[str] = Field(
        default_factory=lambda: ["zh", "en"],
        description="语言提示，默认中英混合",
    )


class ShotSubtitleRenderRequest(BaseModel):
    """``POST /api/v1/commerce/shot-subtitle-render`` 请求体（P3 W18）。

    触发 ``shot_subtitle_render`` worker：把字级时间戳按 SubtitleStyle
    渲染成 ``.ass`` 文件，落 minio + SubtitleTrack。
    """

    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(..., min_length=1, description="字幕所属镜头 ID")
    style_id: str = Field(
        ...,
        min_length=1,
        description="SubtitleStyle ID（如 douyin_default / tiktok_viral / reels_lower_third）",
    )
    word_timestamps: list[dict[str, Any]] = Field(
        ...,
        description="字级时间戳数组：[{text, begin_ms, end_ms}, ...]",
    )
    language_code: str = Field(default="zh-CN", description="字幕语言代码")
    source: str = Field(
        default="tts_word_timestamps",
        description="来源：tts_word_timestamps / asr_paraformer_v2 / manual",
    )


class ChapterAvExportRequest(BaseModel):
    """``POST /api/v1/commerce/chapter-av-export`` 请求体（P3 W19 / P5 W31）。

    触发 ``chapter_av_export`` worker：跨路径合成"配音 + 字幕"成片。
    要求章节内所有 Shot.generated_video_file_id 已就位（裸视频已生成），
    每段 ChapterTimelineSegment 的 subtitle_track_file_id / tts_audio_file_id
    可选——按 audio_strategy 自动分流：silent_with_tts amix TTS、keep_native
    pass-through 原音；缺 TTS 段降级 anullsrc 静音。

    P5 W31 新增 ``audio_mix_mode``：控制是否在合成阶段混入 BGM / SFX。
    优先级：``audio_mix_mode`` > ``ChapterTimelineSegment.bgm_file_id``
    / ``sfx_file_id``。当 mode 为 ``voice_bgm`` 但 segment 缺 BGM 时，
    本段自动 fallback 到 ``voice_only``（写 warning 不阻塞）。
    """

    model_config = ConfigDict(extra="forbid")

    chapter_id: str = Field(..., min_length=1, description="目标章节 ID")
    aspect: str = Field(
        default="9:16",
        description="输出宽高比：9:16（1080×1920）/ 16:9（1280×720）",
    )
    audio_strategy_override: str | None = Field(
        default=None,
        description="覆盖所有镜头 audio_strategy：silent_with_tts / keep_native / null（按各 Shot 字段独立分流）",
    )
    audio_mix_mode: str = Field(
        default="voice_only",
        description=(
            "P5 W31：音轨混合模式（off / voice_only / voice_bgm / full）。"
            "voice_only=W19 默认；voice_bgm=语音+BGM amix weights='1 0.4'；"
            "full=语音+BGM(sidechaincompress ducking)+SFX(amerge 时间轴对齐)；"
            "off=完全静音输出。BGM/SFX 来源由各 segment 的 bgm_file_id/"
            "sfx_file_id 决定，缺失时自动降级。"
        ),
    )


class TaskEnqueueResponse(BaseModel):
    """3 个 commerce/* 异步任务入口的统一响应壳。

    Attributes:
        task_id: 新建 ``GenerationTask`` 的主键，前端用它后续轮询状态。
        task_kind: 任务类型，用于前端区分要展示的进度/结果面板。
        status: 入队后的初始状态，约定固定为 ``"pending"``。
        enqueued_at: 入队时间戳；以 server-side 时间为准，便于排查
            “前端发起 vs 实际投递”的延迟。
    """

    task_id: str = Field(..., description="任务 ID（GenerationTask.id）")
    task_kind: str = Field(
        ...,
        description=(
            "任务类型：product_info_extract / story_script_generate / compliance_check / "
            "chapter_av_plan / tts_generate / asr_subtitle_generate / "
            "shot_subtitle_render / chapter_av_export"
        ),
    )
    status: str = Field(..., description="入队后的初始状态，固定为 'pending'")
    enqueued_at: datetime = Field(..., description="入队时间戳（server-side）")


__all__ = [
    "AsrSubtitleGenerateRequest",
    "ChapterAvExportRequest",
    "ChapterAvPlanRequest",
    "ComplianceCheckRequest",
    "ProductExtractRequest",
    "ScriptGenerateRequest",
    "ShotSubtitleRenderRequest",
    "TaskEnqueueResponse",
    "TtsGenerateRequest",
]
