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
from app.services.film.generated_video import run_video_generation_task
from app.services.studio.chapter_timeline_export_task import run_chapter_timeline_export_task
from app.services.film.shot_frame_prompt_tasks import run_shot_frame_prompt_task
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
# W12-T4: P2 commerce workers — hook/cta/archetype 三个 in-place patch executor，
# 共同消费 StoryVariant.script_breakdown，单次注册集中在此处避免与 W5 系列竞态。
task_executor_registry.register("hook_writer", build_hook_writer_executor())
task_executor_registry.register("cta_writer", build_cta_writer_executor())
task_executor_registry.register(
    "archetype_rewrite", build_archetype_rewrite_executor()
)
