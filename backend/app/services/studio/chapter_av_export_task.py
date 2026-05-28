"""章节级 AV 合成 worker（P3 W19 T19-1）。

为什么存在：
    把 W17 双路径产出（silent_with_tts → CosyVoice TTS / keep_native →
    Paraformer-v2 ASR 反推）+ W18 字幕渲染（``.ass``）+ 各 segment 的
    raw 视频，一次 ffmpeg ``filter_complex`` 合成最终"配音 + 字幕"成片
    （``FileUsageKind.chapter_master_dubbed``），代替老 ``chapter_timeline_export``
    的"裸视频拼接"。

    与老 worker 并存：``chapter_timeline_export`` 标 deprecated 至 v0.7.0
    删除（仍可用于无字幕无音轨的快速合并场景）。

做什么：
    异步 runner 输入 ``run_args``：

    - ``chapter_id`` (str, required): 目标章节 ID。
    - ``aspect`` (str, optional, default ``9:16``): 输出宽高比，``9:16`` 走
      1080×1920，``16:9`` 走 1280×720。
    - ``audio_strategy_override`` (str, optional): 强制覆盖所有 segment 的
      audio_strategy（``silent_with_tts`` / ``keep_native``）；缺省按每个
      ``Shot.audio_strategy`` 字段独立分流。

    输出（写入 ``store.set_result`` 的 dict）：

    - ``file_id``: 最终成片 FileItem ID（type=video）。
    - ``chapter_id``: 章节 ID。
    - ``segment_count``: 实际合成的段数。
    - ``aspect`` / ``fps`` / ``lufs_target``: 实际生效参数（便于排障）。

设计要点：
- 完整复用 hotfix-4 canonical 模板（与 ``chapter_timeline_export_task`` 同形）：
  ``set_status(running)`` → cancel check → 业务 → cancel check → ``set_result`` →
  ``set_status(succeeded)``；失败时 rollback + 独立会话写 failed。
- ``slow`` 队列、1800s 超时（plan 约定）：单章节通常 5-10 段、每段 5s 视频
  + TTS / ASR + 字幕烧录，整体在 3-10 分钟级。
- ffmpeg 命令通过 ``-filter_complex_script`` 落地（filter graph 长度往往
  > 8KB，避免 OS 命令行长度限制）。
- ``ChapterTimelineSegment.subtitle_track_file_id`` / ``tts_audio_file_id``
  缺失时各自降级：无字幕段跳过 ``subtitles=`` 滤镜；无 TTS 段（仅
  silent_with_tts 路径）兜底 ``anullsrc`` 静音轨；keep_native 路径无视
  这些字段直接走原音轨。
- 成片落 ``Shot.dubbed_video_file_id``（每段镜头都更新指向同一章节成片，
  便于前端工作室预览时优先取 dubbed 版本）。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings as app_settings
from app.core import storage
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.studio import (
    Chapter,
    ChapterTimelineSegment,
    FileItem,
    FileType,
    Shot,
)
from app.models.task_links import GenerationTaskLink
from app.models.types import AudioStrategy, FileUsageKind
from app.services.studio.chapter_av_export import (
    EXPORT_RELATION_TYPE,
    EXPORT_RESOURCE_TYPE,
    EXPORT_TASK_KIND,
)
from app.services.studio.chapter_av_export_filter import (
    DEFAULT_FPS,
    LOUDNORM_I,
    PRESET_RESOLUTIONS,
    SegmentFilterSpec,
    TtsClipSpec,
    build_filter_complex,
)
from app.services.studio.chapter_timeline import build_timeline_read
from app.services.studio.chapter_timeline_export import ensure_timeline_exportable
from app.services.studio.chapter_timeline_media import (
    ffprobe_local_file,
    probe_duration_and_audio,
)
from app.services.studio.chapter_timeline_trim import trim_seconds_for_ffmpeg
from app.services.studio.file_usages import upsert_file_usage
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = EXPORT_TASK_KIND
"""注册键：与 ``chapter_av_export.EXPORT_TASK_KIND`` 同源。"""

DEFAULT_TIMEOUT_SECONDS = 1800.0
"""默认超时（秒）：单章节通常 3-10 分钟级，1800s 留 3x 余量。"""

_RUNNING_PROGRESS = 5
"""进入 running 时的初始进度（与 chapter_timeline_export 一致）。"""

_LOAD_PROGRESS = 20
"""加载 segments + 校验文件后、ffmpeg 启动前的进度水位。"""

_SUCCEEDED_PROGRESS = 100

#: 输出对象存储 key 前缀：与 chapter_timeline_export 显式分离便于排查。
_OUTPUT_PREFIX = "generated-videos/chapters"


def _coerce_str(value: object, *, default: str = "") -> str:
    """把 ``run_args`` 中的字符串字段安全规范化（去首尾空白）。"""

    if value is None:
        return default
    return str(value).strip() or default


def _coerce_aspect(value: object) -> Literal["9:16", "16:9"]:
    """``run_args['aspect']`` → 校验后的合法宽高比，缺省 9:16。"""

    raw = _coerce_str(value, default="9:16")
    if raw not in PRESET_RESOLUTIONS:
        raise ValueError(
            f"unsupported aspect: {raw!r}; supported: "
            f"{sorted(PRESET_RESOLUTIONS)}"
        )
    return raw  # type: ignore[return-value]


def _coerce_audio_strategy(
    value: object,
    *,
    fallback: AudioStrategy = AudioStrategy.silent_with_tts,
) -> AudioStrategy:
    """把 ``Shot.audio_strategy`` 或 run_args override 兜底为 enum。

    与 W17 收尾 build_run_args 的 SQLAlchemy String 列回读 coerce 同源。
    """

    if isinstance(value, AudioStrategy):
        return value
    raw = _coerce_str(value)
    if not raw:
        return fallback
    try:
        return AudioStrategy(raw)
    except ValueError:
        return fallback


async def _download_file_or_raise(
    file_obj: FileItem | None, *, dest: Path, label: str
) -> Path:
    """把单个 FileItem 内容下载到本地 dest；缺失或为空抛 RuntimeError。"""

    if file_obj is None or not file_obj.storage_key:
        raise RuntimeError(f"{label} 缺少 FileItem 或 storage_key")
    data = await storage.download_file(key=file_obj.storage_key)
    if not data:
        raise RuntimeError(f"{label} 下载结果为空: {file_obj.id}")
    dest.write_bytes(data)
    return dest


async def _resolve_segment_resources(
    session: AsyncSession,
    *,
    chapter_id: str,
) -> list[tuple[ChapterTimelineSegment, Shot, FileItem, FileItem | None, FileItem | None]]:
    """加载章节内所有 segment 及其依赖 FileItem（按 position 排序）。

    返回列表元素为 ``(segment, shot, video_file, ass_file_or_none,
    tts_audio_file_or_none)``。视频文件缺失抛错（合成必须项），字幕与
    TTS 缺失允许（worker 内部走降级路径）。
    """

    seg_rows = (
        await session.execute(
            select(ChapterTimelineSegment)
            .where(ChapterTimelineSegment.chapter_id == chapter_id)
            .order_by(ChapterTimelineSegment.position)
        )
    ).scalars().all()
    if not seg_rows:
        raise RuntimeError("章节时间线为空，无法合成")

    out: list[
        tuple[ChapterTimelineSegment, Shot, FileItem, FileItem | None, FileItem | None]
    ] = []
    for seg in seg_rows:
        shot = await session.get(Shot, seg.shot_id)
        if shot is None or shot.chapter_id != chapter_id:
            raise RuntimeError(f"镜头不属于本章节: {seg.shot_id}")

        if not shot.generated_video_file_id:
            raise RuntimeError(f"镜头缺少裸视频成片: {seg.shot_id}")
        video_file = await session.get(FileItem, shot.generated_video_file_id)
        if video_file is None or video_file.type != FileType.video or not video_file.storage_key:
            raise RuntimeError(f"镜头视频 FileItem 无效: {seg.shot_id}")

        ass_file: FileItem | None = None
        if seg.subtitle_track_file_id:
            ass_file = await session.get(FileItem, seg.subtitle_track_file_id)

        tts_file: FileItem | None = None
        if seg.tts_audio_file_id:
            tts_file = await session.get(FileItem, seg.tts_audio_file_id)

        out.append((seg, shot, video_file, ass_file, tts_file))
    return out


async def _build_filter_specs(
    *,
    seg_resources: list[
        tuple[ChapterTimelineSegment, Shot, FileItem, FileItem | None, FileItem | None]
    ],
    tmp_path: Path,
    audio_strategy_override: AudioStrategy | None,
) -> tuple[list[SegmentFilterSpec], list[Path], list[Path | None]]:
    """下载所有视频/TTS 到本地 + 构造 SegmentFilterSpec + 返回 input 文件顺序。

    输入顺序约定：``-i video_0 video_1 ... video_N tts_0 tts_1 ... tts_M``。
    每段 segment 的 ``video_input_index`` 即其 0-based segment 序号，
    每段 TTS（若存在）顺序追加到视频之后并赋全局递增 input_index。

    Returns:
        (specs, video_paths, ass_paths)：
        - specs: 已计算好 input_index / trim 的 ``SegmentFilterSpec`` 列表；
        - video_paths: 视频本地文件路径，按 spec.video_input_index 顺序；
        - ass_paths: 字幕文件本地路径（与 specs 一一对应，None 表示无字幕）。
    """

    n_segments = len(seg_resources)
    video_paths: list[Path] = []
    ass_paths: list[Path | None] = []
    tts_paths: list[Path] = []

    specs: list[SegmentFilterSpec] = []
    next_tts_input_index = n_segments

    for idx, (seg, shot, video_file, ass_file, tts_file) in enumerate(seg_resources):
        # 下载视频。
        video_dest = tmp_path / f"video_{idx:04d}.mp4"
        await _download_file_or_raise(video_file, dest=video_dest, label=f"shot {shot.id} 视频")
        video_paths.append(video_dest)

        # 下载字幕（可选）。
        ass_dest: Path | None = None
        if ass_file is not None:
            ass_dest = tmp_path / f"sub_{idx:04d}.ass"
            await _download_file_or_raise(ass_file, dest=ass_dest, label=f"shot {shot.id} 字幕")
        ass_paths.append(ass_dest)

        # 决定本段 audio_strategy（override 优先，否则按 Shot 字段）。
        if audio_strategy_override is not None:
            audio_strategy = audio_strategy_override
        else:
            audio_strategy = _coerce_audio_strategy(shot.audio_strategy)

        # 计算 trim_start_s / trim_end_s（复用 chapter_timeline 现成工具）。
        probe = await ffprobe_local_file(video_dest)
        dur_s, _ = probe_duration_and_audio(probe)
        if dur_s <= 0:
            raise RuntimeError(f"无法解析视频时长: shot_id={shot.id}")
        trim_start_s, trim_end_s = trim_seconds_for_ffmpeg(
            dur_s, seg.trim_start_ms, seg.trim_end_ms
        )
        duration_s = trim_end_s - trim_start_s
        if duration_s <= 0:
            raise RuntimeError(f"裁剪后时长无效: shot_id={shot.id}")

        # 仅 silent_with_tts 路径需要下载 TTS（keep_native 直接用视频原音轨）。
        tts_clips: list[TtsClipSpec] = []
        if audio_strategy == AudioStrategy.silent_with_tts and tts_file is not None:
            tts_dest = tmp_path / f"tts_{idx:04d}_0.mp3"
            await _download_file_or_raise(tts_file, dest=tts_dest, label=f"shot {shot.id} TTS")
            tts_paths.append(tts_dest)
            tts_clips.append(
                TtsClipSpec(input_index=next_tts_input_index, offset_ms=0)
            )
            next_tts_input_index += 1

        specs.append(
            SegmentFilterSpec(
                index=idx,
                video_input_index=idx,
                trim_start_s=trim_start_s,
                trim_end_s=trim_end_s,
                duration_s=duration_s,
                audio_strategy=audio_strategy,
                ass_path=ass_dest,
                tts_clips=tuple(tts_clips),
            )
        )

    return specs, video_paths + tts_paths, ass_paths


async def _run_ffmpeg_av_export(
    *,
    inputs: list[Path],
    filter_complex: str,
    output: Path,
    tmp_path: Path,
) -> None:
    """启动 ffmpeg 子进程执行合成；filter_complex 写入 script 文件以避免命令行长度限制。

    输出参数固定为：libx264 medium crf 20 + aac 192k + 30fps + faststart，
    与 W19 librarian 调研报告推荐的"通用流媒体"配方一致。
    """

    script_path = tmp_path / ".filter_complex.txt"
    script_path.write_text(filter_complex, encoding="utf-8")

    args: list[str] = ["ffmpeg", "-y"]
    for path in inputs:
        args += ["-i", str(path)]
    args += [
        "-filter_complex_script",
        str(script_path),
        "-map",
        "[vc]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-r",
        str(DEFAULT_FPS),
        str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"ffmpeg chapter_av_export 失败: {msg}")


#: 一致性前置门：consistency_status 视为合格的取值集合。
#:
#: ``pass`` / ``warning`` 直接放行；``None`` 兜底视为 warning（避免 W27 之前
#: 未跑过 threshold_engine 的旧数据卡死导出主流程）。``fail`` 是唯一会触发
#: 422 阻塞的取值。
_CONSISTENCY_GATE_OK: frozenset[str | None] = frozenset({"pass", "warning", None})

#: 422 detail.code：前端可据此识别"是一致性前置门拦截，而非通用 422"。
CONSISTENCY_GATE_ERROR_CODE = "consistency_gates_failed"


def _assert_consistency_gates_pass(
    chapter_id: str,
    shots: list[Shot],
    settings: Settings | None = None,
) -> None:
    """章节级 AV 合成前置门：消耗的所有 shots 一致性必须 ≥ warning。

    为什么存在：
        T27-2 已为 :class:`Shot` 落了 ``consistency_status`` 字段；导出 worker
        会把每个 shot 的视频喂进 ffmpeg 合成最终成片，若任一 shot 被 DINOv2
        判为 ``fail`` 仍参与合成，最终交付物会带瑕疵。本前置门把"质量门"
        前移到入队/启动阶段，让用户先把 ``fail`` 的 shot 重生为 ≥ warning，
        而不是等成片渲染完再返工。

    判定规则（与 W27-T2 :mod:`threshold_engine` 对齐）：
        - ``shot.consistency_status == "fail"`` → 收集进 ``failing_shot_ids``
        - ``shot.consistency_status in {"pass", "warning"}`` → 放行
        - ``shot.consistency_status is None`` → 兜底视为 warning，**不**阻塞
          （避免 W27 之前未跑过 threshold_engine 的旧数据全部卡死）

    Args:
        chapter_id: 目标章节 ID，仅用于错误响应中回显。
        shots: 该章节按 timeline 顺序参与合成的 :class:`Shot` 列表；调用方
            负责加载（worker 走 ``_resolve_segment_resources``，路由层可走
            其它查询）。空列表直接放行——空章节无 fail 也无可阻塞对象。
        settings: 应用配置（可注入便于测试）；缺省取全局 :data:`app_settings`。
            ``settings.chapter_av_export_bypass_consistency=True`` 时整个前置
            门会被跳过（应急通道，env: ``CHAPTER_AV_EXPORT_BYPASS_CONSISTENCY=1``）。

    Raises:
        HTTPException: 任一 shot 的 ``consistency_status == "fail"``。响应
            ``status_code=422``，``detail`` 为带结构化字段的 dict::

                {
                    "code": "consistency_gates_failed",
                    "chapter_id": "<chapter_id>",
                    "failing_shot_ids": ["<shot_id_1>", ...],
                    "message": "<人类可读提示>",
                }

            前端可据 ``failing_shot_ids`` 触发批量 regen（借
            :func:`enqueue_video_generation` chain）。
    """

    effective_settings = settings if settings is not None else app_settings

    # 显式 bypass：power-user / 排障应急通道。一旦开启，整个前置门短路。
    if effective_settings.chapter_av_export_bypass_consistency:
        return

    failing_shot_ids: list[str] = [
        shot.id for shot in shots if shot.consistency_status not in _CONSISTENCY_GATE_OK
    ]

    if not failing_shot_ids:
        return

    raise HTTPException(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": CONSISTENCY_GATE_ERROR_CODE,
            "chapter_id": chapter_id,
            "failing_shot_ids": failing_shot_ids,
            "message": (
                f"章节 {chapter_id} 中有 {len(failing_shot_ids)} 个镜头视觉一致性"
                "判定为 fail，请先重生这些镜头后再发起 AV 合成"
            ),
        },
    )


async def run_chapter_av_export_task(task_id: str, run_args: dict[str, Any]) -> None:
    """异步 runner：合成章节"配音 + 字幕"成片。

    异常处理：
        与 ``chapter_timeline_export_task`` 一致：try 中 rollback、独立会话
        写 failed、再向上抛由 ``AbstractAsyncDelegatingExecutor`` 转换为
        Celery 失败状态。
    """

    chapter_id = _coerce_str(run_args.get("chapter_id"))
    if not chapter_id:
        raise RuntimeError("run_args 缺少 chapter_id")
    aspect = _coerce_aspect(run_args.get("aspect"))
    override_value = run_args.get("audio_strategy_override")
    audio_strategy_override = (
        _coerce_audio_strategy(override_value) if override_value else None
    )

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running", chapter_id=chapter_id)

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_load")
                return

            # Step 1: 通用导出前置校验（复用 chapter_timeline_export 的校验函数，
            # 但走 ChapterTimelineSegment 直查，避免 build_timeline_read 引入的
            # auto-append 行为干扰 av 路径）。
            read = await build_timeline_read(session, chapter_id)
            ensure_timeline_exportable(read)

            chapter = await session.get(Chapter, chapter_id)
            if chapter is None:
                raise RuntimeError(f"章节不存在: {chapter_id}")
            project_id = chapter.project_id

            seg_resources = await _resolve_segment_resources(
                session, chapter_id=chapter_id
            )

            # W27-T4 一致性前置门：消耗的所有 shots 必须 ≥ warning，否则直接
            # 抛 422 短路，由外层异常路径写 failed + str(HTTPException) 入 error。
            _assert_consistency_gates_pass(
                chapter_id,
                [shot for _seg, shot, *_ in seg_resources],
            )

            await store.set_progress(task_id, _LOAD_PROGRESS)
            await session.commit()

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_load")
                return

            # Step 2: 在临时目录下载所有依赖资源 + 构造 ffmpeg filter graph + 执行。
            with tempfile.TemporaryDirectory(prefix=f"jf-av-export-{task_id}-") as tmp:
                tmp_path = Path(tmp)
                specs, ordered_inputs, _ass_paths = await _build_filter_specs(
                    seg_resources=seg_resources,
                    tmp_path=tmp_path,
                    audio_strategy_override=audio_strategy_override,
                )
                filter_complex = build_filter_complex(
                    specs,
                    aspect=aspect,
                    fps=DEFAULT_FPS,
                    lufs_target=LOUDNORM_I,
                )
                output_path = tmp_path / "master.mp4"
                await _run_ffmpeg_av_export(
                    inputs=ordered_inputs,
                    filter_complex=filter_complex,
                    output=output_path,
                    tmp_path=tmp_path,
                )
                master_bytes = output_path.read_bytes()
                if not master_bytes:
                    raise RuntimeError("chapter_av_export 输出为空文件")

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_ffmpeg")
                return

            # Step 3: 上传 minio + 落 FileItem + 反查 GenerationTaskLink + FileUsage。
            out_key = (
                f"{_OUTPUT_PREFIX}/{chapter_id}/av-export/{uuid.uuid4().hex}.mp4"
            )
            info = await storage.upload_file(
                key=out_key,
                data=master_bytes,
                content_type="video/mp4",
                extra_args={"ACL": "public-read"},
            )

            new_file_id = uuid.uuid4().hex
            session.add(
                FileItem(
                    id=new_file_id,
                    type=FileType.video,
                    name=f"chapter-{chapter_id}-av-master",
                    thumbnail=info.url,
                    tags=["chapter_av_export", "dubbed"],
                    storage_key=out_key,
                ),
            )

            # 反查 GenerationTaskLink → 回写 file_id（路由层创建时未知 file_id）。
            link_stmt = (
                select(GenerationTaskLink)
                .where(
                    GenerationTaskLink.task_id == task_id,
                    GenerationTaskLink.resource_type == EXPORT_RESOURCE_TYPE,
                    GenerationTaskLink.relation_type == EXPORT_RELATION_TYPE,
                    GenerationTaskLink.relation_entity_id == chapter_id,
                )
                .limit(1)
            )
            link_row = (await session.execute(link_stmt)).scalars().first()
            if link_row is not None:
                link_row.file_id = new_file_id

            # 同步 file_usages 行：新枚举 chapter_master_dubbed 区分 timeline_export
            # 的 chapter_master_video 产物。
            await upsert_file_usage(
                session,
                file_id=new_file_id,
                project_id=project_id,
                chapter_id=chapter_id,
                shot_id=None,
                usage_kind=FileUsageKind.chapter_master_dubbed,
                source_ref=f"chapter:{chapter_id}:av_export:{task_id}",
            )

            # 把成片指针落到每一段对应的 Shot.dubbed_video_file_id，便于前端
            # 工作室预览时优先取 dubbed 版本。
            for seg, shot, *_ in seg_resources:
                shot.dubbed_video_file_id = new_file_id

            await store.set_result(
                task_id,
                {
                    "file_id": new_file_id,
                    "chapter_id": chapter_id,
                    "segment_count": len(seg_resources),
                    "aspect": aspect,
                    "fps": DEFAULT_FPS,
                    "lufs_target": LOUDNORM_I,
                },
            )

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_persist")
                return

            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                chapter_id=chapter_id,
                segment_count=len(seg_resources),
                file_id=new_file_id,
            )
        except Exception as exc:  # noqa: BLE001 - 与既有 worker 模板保持一致
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


def build_chapter_av_export_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 chapter_av_export 执行器实例。

    Returns:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，
        ``task_kind = chapter_av_export``，``timeout_seconds = 1800``。
    """

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_chapter_av_export_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_chapter_av_export_executor",
    "run_chapter_av_export_task",
]
