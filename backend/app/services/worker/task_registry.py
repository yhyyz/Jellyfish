"""任务执行器注册表。

职责：
- 通过 task_kind 解析到具体 WorkerTaskExecutor；
- 将任务编排层与 worker 执行层解耦；
- 为后续图片 / 视频 / 文本任务统一执行入口预留注册点。
"""

from __future__ import annotations

from app.services.commerce.archetype_rewrite_worker import (
    build_archetype_rewrite_executor,
)
from app.services.commerce.compliance_check_worker import (
    DEFAULT_TIMEOUT_SEC as COMPLIANCE_CHECK_TIMEOUT_SEC,
    TASK_KIND as COMPLIANCE_CHECK_TASK_KIND,
    run_compliance_check_task,
)
from app.services.commerce.cta_writer_worker import build_cta_writer_executor
from app.services.commerce.hook_writer_worker import build_hook_writer_executor
from app.services.commerce.product_info_extract_worker import (
    DEFAULT_TIMEOUT_SECONDS as PRODUCT_INFO_EXTRACT_TIMEOUT,
    TASK_KIND as PRODUCT_INFO_EXTRACT_TASK_KIND,
    run_product_info_extract_task,
)
from app.services.commerce.story_script_generate_worker import (
    build_story_script_generate_executor,
)
from app.services.commerce.story_video_batch_generate_worker import (
    build_story_video_batch_generate_executor,
)
from app.services.film.generated_video import run_video_generation_task
from app.services.studio.asr_subtitle_generate_worker import (
    build_asr_subtitle_generate_executor,
)
from app.services.studio.chapter_av_export_task import (
    build_chapter_av_export_executor,
)
from app.services.studio.chapter_av_plan_worker import build_chapter_av_plan_executor
from app.services.studio.shot_subtitle_render_worker import (
    build_shot_subtitle_render_executor,
)
from app.services.studio.chapter_timeline_export_task import run_chapter_timeline_export_task
from app.services.studio.tts_generate_worker import build_tts_generate_executor
from app.services.film.shot_frame_prompt_tasks import run_shot_frame_prompt_task
from app.services.visual_consistency.consistency_worker import (
    DEFAULT_TIMEOUT_SEC as SHOT_CONSISTENCY_TIMEOUT_SEC,
    TASK_KIND as SHOT_CONSISTENCY_TASK_KIND,
    run_shot_consistency_check_task,
)
from app.services.script_processing_worker import (
    CharacterPortraitTaskExecutor,
    ConsistencyTaskExecutor,
    CostumeInfoTaskExecutor,
    DivideTaskExecutor,
    ExtractTaskExecutor,
    PropInfoTaskExecutor,
    SceneInfoTaskExecutor,
    ScriptOptimizationTaskExecutor,
    ScriptSimplificationTaskExecutor,
)
from app.services.studio.image_task_runner import run_image_generation_task
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor, AbstractWorkerTaskExecutor


class TaskExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, AbstractWorkerTaskExecutor] = {}

    def register(self, task_kind: str, executor: AbstractWorkerTaskExecutor) -> None:
        self._executors[task_kind] = executor

    def resolve(self, task_kind: str) -> AbstractWorkerTaskExecutor:
        try:
            return self._executors[task_kind]
        except KeyError as exc:  # pragma: no cover - 显式错误路径
            raise RuntimeError(f"Unsupported task_kind: {task_kind}") from exc


task_executor_registry = TaskExecutorRegistry()

task_executor_registry.register("script_divide", DivideTaskExecutor())
task_executor_registry.register("script_extract", ExtractTaskExecutor())
task_executor_registry.register("script_consistency", ConsistencyTaskExecutor())
task_executor_registry.register("script_character_portrait", CharacterPortraitTaskExecutor())
task_executor_registry.register("script_prop_info", PropInfoTaskExecutor())
task_executor_registry.register("script_scene_info", SceneInfoTaskExecutor())
task_executor_registry.register("script_costume_info", CostumeInfoTaskExecutor())
task_executor_registry.register("script_optimize", ScriptOptimizationTaskExecutor())
task_executor_registry.register("script_simplify", ScriptSimplificationTaskExecutor())
task_executor_registry.register(
    "video_generation",
    AbstractAsyncDelegatingExecutor(
        task_kind="video_generation",
        runner=run_video_generation_task,
        timeout_seconds=3600.0,
    ),
)
task_executor_registry.register(
    "chapter_timeline_export",
    AbstractAsyncDelegatingExecutor(
        task_kind="chapter_timeline_export",
        runner=run_chapter_timeline_export_task,
        timeout_seconds=7200.0,
    ),
)
task_executor_registry.register(
    "image_generation",
    AbstractAsyncDelegatingExecutor(
        task_kind="image_generation",
        runner=run_image_generation_task,
        timeout_seconds=1800.0,
    ),
)
task_executor_registry.register(
    "shot_frame_prompt",
    AbstractAsyncDelegatingExecutor(
        task_kind="shot_frame_prompt",
        runner=run_shot_frame_prompt_task,
        timeout_seconds=600.0,
    ),
)
task_executor_registry.register(
    PRODUCT_INFO_EXTRACT_TASK_KIND,
    AbstractAsyncDelegatingExecutor(
        task_kind=PRODUCT_INFO_EXTRACT_TASK_KIND,
        runner=run_product_info_extract_task,
        timeout_seconds=PRODUCT_INFO_EXTRACT_TIMEOUT,
    ),
)
task_executor_registry.register(
    COMPLIANCE_CHECK_TASK_KIND,
    AbstractAsyncDelegatingExecutor(
        task_kind=COMPLIANCE_CHECK_TASK_KIND,
        runner=run_compliance_check_task,
        timeout_seconds=COMPLIANCE_CHECK_TIMEOUT_SEC,
    ),
)
task_executor_registry.register(
    "story_script_generate",
    build_story_script_generate_executor(),
)
task_executor_registry.register(
    "story_video_batch_generate",
    build_story_video_batch_generate_executor(),
)
# W12-T4: P2 commerce workers — hook/cta/archetype 三个 in-place patch executor，
# 共同消费 StoryVariant.script_breakdown，单次注册集中在此处避免与 W5 系列竞态。
task_executor_registry.register("hook_writer", build_hook_writer_executor())
task_executor_registry.register("cta_writer", build_cta_writer_executor())
task_executor_registry.register(
    "archetype_rewrite", build_archetype_rewrite_executor()
)
# P3 W17 T17-5: TTS 合成 worker（fast 队列，300s 超时），cache 命中走快速分支，
# miss 时调 DashScopeTtsApiAdapter.synthesize 并落 FileItem + TtsCache 行。
task_executor_registry.register("tts_generate", build_tts_generate_executor())
# P3 W17 T17-7: 章节级 AV plan worker（slow 队列，7200s 超时），
# Decision F 决策树编排：estimate → speed_adjust → llm_rewrite → hold。
task_executor_registry.register("chapter_av_plan", build_chapter_av_plan_executor())
# P3 W17 收尾（Decision D 修订）: ASR 字幕反推 worker（fast 队列，600s 超时），
# 用 DashScope Paraformer-v2 对 keep_native 路径生成视频的原音反推字级时间戳。
task_executor_registry.register(
    "asr_subtitle_generate", build_asr_subtitle_generate_executor()
)
# P3 W18: 字幕渲染 worker（fast 队列，120s 超时），把字级时间戳 + SubtitleStyle
# 渲染为 .ass 文件，落 minio + 写 SubtitleTrack 行，供下游章节合成阶段烧录。
task_executor_registry.register(
    "shot_subtitle_render", build_shot_subtitle_render_executor()
)
# P3 W19: 章节级 AV 合成 worker（slow 队列，1800s 超时），按 Shot.audio_strategy
# 分流（amix TTS / 原音 pass-through）+ ASS 硬烧 + loudnorm 响度归一化，
# 产出"配音 + 字幕"最终成片，与老 chapter_timeline_export 并存（后者标 deprecated）。
task_executor_registry.register(
    "chapter_av_export", build_chapter_av_export_executor()
)
# P4 W27-T1: 视觉一致性 worker（slow 队列，600s 超时），ffmpeg 抽 6 帧 ->
# DINOv2 sidecar embed -> 与 ProductImage(front/three_quarter) cosine ->
# 写 shot.consistency_score。ML stack 完全在 sidecar，主镜像不受影响。
task_executor_registry.register(
    SHOT_CONSISTENCY_TASK_KIND,
    AbstractAsyncDelegatingExecutor(
        task_kind=SHOT_CONSISTENCY_TASK_KIND,
        runner=run_shot_consistency_check_task,
        timeout_seconds=SHOT_CONSISTENCY_TIMEOUT_SEC,
    ),
)
