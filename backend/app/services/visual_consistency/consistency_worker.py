"""``shot_consistency_check`` task_kind 异步执行器（P4 W27-T1）。

为什么存在：
    - 视觉一致性是 P4 的核心质量门：把 ``shot.dubbed_video_file_id`` 对应
      的最终成片与 ``shot.product`` 的参考图（front / three_quarter）做
      cosine similarity，结果落到 ``shot.consistency_score``；
    - 与 ``compliance_check_worker`` 的风格保持一致——本模块只暴露一个
      纯净 async runner，超时 / 取消 / 状态机由
      :class:`AbstractAsyncDelegatingExecutor` 在 task_registry 上层封装。

算法（与 P4 规范对齐）：
    1. 取 Shot 与对应的 dubbed video FileItem；
    2. 下载 mp4 到本地 tmp 目录；
    3. ffprobe 取总帧数 → 计算 step → ffmpeg 抽 N=6 帧；
    4. 每帧 → POST /embed 得 768-dim 向量；
    5. 平均 N 帧得 shot embedding（再 L2 归一）；
    6. 取 ProductImage（FRONT 优先，缺则 THREE_QUARTER） → POST /embed；
    7. cosine similarity → 写 shot.consistency_score；
    8. 缺 reference / 抽帧 0 / sidecar 不可达 → score=null + 显式 reason，
       不抛异常。

边界：
    - 不实装阈值判定（W27-T2 范围）；
    - 不在 ``chapter_av_export`` 里做 pre-gate（W27-T4 范围）；
    - 不在主 backend 镜像引入 torch（DECISION D-VISION-DEPLOY=sidecar）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.contracts.visual_consistency import (
    DINOV2_EMBED_DIM,
    ConsistencyScoreResult,
)
from app.core.db import async_session_maker
from app.core.integrations.dinov2.client import (
    Dinov2HttpClient,
    Dinov2SidecarError,
    Dinov2SidecarUnavailable,
    build_default_dinov2_client,
)
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.commerce_assets import ProductImage, ProjectProductLink
from app.models.studio_prompts_files_timeline import FileItem
from app.models.studio_shots import Shot
from app.models.types import AssetViewAngle
from app.services.visual_consistency.sampler import (
    DEFAULT_FRAME_COUNT,
    FrameSamplingPlan,
    build_probe_args,
    build_sample_args,
    make_plan,
    parse_probe_total_frames,
)
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


#: 该执行器在任务系统中的 ``task_kind`` 主键。
TASK_KIND: str = "shot_consistency_check"

#: 默认硬超时（秒）。视频下载 + 6 次 sidecar 调用，本地 ffmpeg 抽帧；
#: P4 默认 600s 足够覆盖 60s 短剧 + CPU 推理路径，由
#: :class:`AbstractAsyncDelegatingExecutor` 强制兜底。
DEFAULT_TIMEOUT_SEC: float = 600.0

#: ProductImage 选取顺序：front 优先，缺则 three_quarter；都没有则降级。
_REFERENCE_VIEW_ANGLE_FALLBACK: tuple[AssetViewAngle, ...] = (
    AssetViewAngle.front,
    AssetViewAngle.three_quarter,
)

#: ConsistencyScoreResult.reason 的标准化字面量。
_REASON_NO_REFERENCE = "no_reference"
_REASON_NO_FRAMES = "no_frames"
_REASON_SIDECAR_UNAVAILABLE = "sidecar_unavailable"
_REASON_INVALID_VIDEO = "invalid_video"


# --------------------------------------------------------------------------- #
# DB 加载工具
# --------------------------------------------------------------------------- #


async def _load_shot_or_raise(session: AsyncSession, shot_id: str) -> Shot:
    """取 Shot；不存在直接抛 ValueError，让 worker 走失败路径。"""

    shot = await session.get(Shot, shot_id)
    if shot is None:
        raise ValueError(f"Shot not found: {shot_id}")
    return shot


async def _load_video_file_or_raise(
    session: AsyncSession, *, shot: Shot
) -> FileItem:
    """取 shot.dubbed_video_file_id 对应的 mp4 FileItem。

    优先取 dubbed（最终成片）；缺失时回退到 generated_video（裸视频），
    与 P4 主流程对齐——consistency 关心的是最终交付内容，dubbed 缺失说明
    chapter_av_export 还没跑过，此时回退到裸视频也能给出可用的 score。
    """

    file_id = shot.dubbed_video_file_id or shot.generated_video_file_id
    if not file_id:
        raise ValueError(
            f"Shot has no dubbed_video_file_id nor generated_video_file_id: {shot.id}"
        )
    file_obj = await session.get(FileItem, file_id)
    if file_obj is None or not file_obj.storage_key:
        raise ValueError(f"FileItem invalid for shot {shot.id}: file_id={file_id}")
    return file_obj


async def _resolve_reference_image(
    session: AsyncSession, *, shot: Shot
) -> tuple[FileItem | None, AssetViewAngle | None]:
    """根据 shot 反查 ProductImage（front 优先，three_quarter 兜底）。

    解析路径：
        Shot → Chapter.project_id → ProjectProductLink（按 shot/chapter/project
        粒度逐层放宽） → Product → ProductImage(FRONT or THREE_QUARTER)。

    Returns:
        ``(file_item, view_angle)``。两者全为 ``None`` 表示没有可用参考图，
        worker 会把 score 写成 ``None``。
    """

    chapter = await _load_chapter(session, chapter_id=shot.chapter_id)
    if chapter is None:
        return None, None

    product_id = await _resolve_product_id_for_shot(
        session,
        shot_id=shot.id,
        chapter_id=shot.chapter_id,
        project_id=chapter.project_id,
    )
    if product_id is None:
        return None, None

    for angle in _REFERENCE_VIEW_ANGLE_FALLBACK:
        stmt = (
            select(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.view_angle == angle,
                ProductImage.file_id.is_not(None),
            )
            .order_by(ProductImage.is_primary.desc(), ProductImage.id.asc())
        )
        product_image = (await session.execute(stmt)).scalars().first()
        if product_image is None or product_image.file_id is None:
            continue
        file_obj = await session.get(FileItem, product_image.file_id)
        if file_obj is not None and file_obj.storage_key:
            return file_obj, angle
    return None, None


async def _load_chapter(session: AsyncSession, *, chapter_id: str) -> Any:
    """局部 import 避免顶层 import cycle（Chapter 与 Shot 在不同 module）。"""

    from app.models.studio_projects import Chapter

    return await session.get(Chapter, chapter_id)


async def _resolve_product_id_for_shot(
    session: AsyncSession,
    *,
    shot_id: str,
    chapter_id: str,
    project_id: str,
) -> str | None:
    """按 shot → chapter → project 三级粒度找 ProjectProductLink.product_id。

    与 ``ProjectProductLink`` 唯一约束 ``(product_id, project_id, chapter_id,
    shot_id)`` 配合：scope 越窄越优先匹配，命中即返回。
    """

    # Shot 级。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.shot_id == shot_id,
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id

    # Chapter 级（shot_id 为空）。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.chapter_id == chapter_id,
        ProjectProductLink.shot_id.is_(None),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id

    # Project 级（chapter / shot 都空）。
    stmt = select(ProjectProductLink).where(
        ProjectProductLink.project_id == project_id,
        ProjectProductLink.chapter_id.is_(None),
        ProjectProductLink.shot_id.is_(None),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row.product_id
    return None


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe 子进程封装（可在测试中 monkeypatch）
# --------------------------------------------------------------------------- #


async def _run_subprocess(args: list[str], *, timeout_s: float) -> tuple[int, bytes, bytes]:
    """统一封装 asyncio.create_subprocess_exec。

    - 把 stdout / stderr 都收回，便于失败时把 stderr 写日志；
    - 对 ``timeout_s`` 进行硬约束，超时直接 kill 子进程。
    """

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout or b"", stderr or b""


async def _probe_total_frames(*, input_path: Path) -> int:
    """用 ffprobe 取总帧数；失败返回 0（由 ``compute_step`` 回退）。"""

    args = build_probe_args(input_path=input_path)
    try:
        rc, stdout, stderr = await _run_subprocess(args, timeout_s=30.0)
    except FileNotFoundError:
        logger.warning("ffprobe binary not found on PATH")
        return 0
    except asyncio.TimeoutError:
        logger.warning("ffprobe timed out: %s", input_path)
        return 0
    if rc != 0:
        logger.warning(
            "ffprobe failed rc=%d stderr=%s",
            rc,
            stderr.decode("utf-8", errors="replace")[:500],
        )
        return 0
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return 0
    return parse_probe_total_frames(payload)


async def _sample_frames(
    *,
    plan: FrameSamplingPlan,
) -> list[Path]:
    """跑 ffmpeg 抽帧，返回实际产出的帧文件路径列表。"""

    args = build_sample_args(plan)
    try:
        rc, _stdout, stderr = await _run_subprocess(args, timeout_s=120.0)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg binary not found on PATH") from exc

    if rc != 0:
        msg = stderr.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"ffmpeg sample failed rc={rc}: {msg}")

    frames: list[Path] = []
    parent = plan.output_pattern.parent
    pattern_name = plan.output_pattern.name
    for idx in range(1, plan.target_count + 1):
        candidate = parent / pattern_name.replace("%d", str(idx))
        if candidate.exists() and candidate.stat().st_size > 0:
            frames.append(candidate)
    return frames


# --------------------------------------------------------------------------- #
# embedding 与均值
# --------------------------------------------------------------------------- #


async def _embed_image_file(
    client: Dinov2HttpClient, *, image_path: Path
) -> list[float]:
    """把单个本地图片文件读出 → base64 → 调 sidecar /embed-json。"""

    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    resp = await client.embed_b64(image_b64=b64)
    return resp.embedding


async def _embed_storage_file(
    client: Dinov2HttpClient,
    *,
    storage_key: str,
) -> list[float]:
    """对 minio / S3 上的图片做 embedding。"""

    raw = await storage.download_file(key=storage_key)
    if not raw:
        raise RuntimeError(f"empty storage object: {storage_key}")
    b64 = base64.b64encode(raw).decode("ascii")
    resp = await client.embed_b64(image_b64=b64)
    return resp.embedding


def _average_embeddings(vectors: list[list[float]]) -> list[float]:
    """对多个 768-dim 向量取均值后再 L2 归一。

    每帧自身已 L2 归一；均值不一定是单位向量，所以再做一次归一保证后续
    cosine = dot 的等价性。

    刻意不引入 numpy（主 backend 镜像不包含 numpy 依赖）；纯 Python 在
    DINOV2_EMBED_DIM=768 × 6 帧规模下毫秒级足够。
    """

    if not vectors:
        raise ValueError("cannot average zero vectors")
    dim = len(vectors[0])
    if dim != DINOV2_EMBED_DIM:
        raise ValueError(
            f"expected vectors of length {DINOV2_EMBED_DIM}, got {dim}"
        )
    sums = [0.0] * dim
    for vec in vectors:
        if len(vec) != dim:
            raise ValueError(
                f"inconsistent vector dim: expected {dim}, got {len(vec)}"
            )
        for i, value in enumerate(vec):
            sums[i] += float(value)
    count = len(vectors)
    mean = [s / count for s in sums]
    norm = math.sqrt(sum(m * m for m in mean))
    if norm == 0.0:
        return mean
    return [m / norm for m in mean]


def _cosine(a: list[float], b: list[float]) -> float:
    """两向量的余弦相似度；输入向量已 L2 归一时退化为点积。"""

    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a_sq += fx * fx
        norm_b_sq += fy * fy
    if norm_a_sq == 0.0 or norm_b_sq == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a_sq * norm_b_sq)


# --------------------------------------------------------------------------- #
# 主流程：纯函数，便于在测试中单独验证
# --------------------------------------------------------------------------- #


async def _compute_consistency_score(  # pylint: disable=too-many-return-statements
    *,
    session: AsyncSession,
    shot: Shot,
    client: Dinov2HttpClient,
    tmp_dir: Path,
    target_count: int = DEFAULT_FRAME_COUNT,
) -> ConsistencyScoreResult:
    """从 Shot 起点跑完抽帧 → embed → cosine 全流程。

    返回 :class:`ConsistencyScoreResult`：``score`` 可空（缺 reference /
    抽帧失败 / sidecar 不可达），不抛异常给上层，由 worker 决定如何写库。
    """

    try:
        video_file = await _load_video_file_or_raise(session, shot=shot)
    except ValueError as exc:
        logger.warning("shot %s: %s", shot.id, exc)
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=0,
            reference_view_angle=None,
            reference_file_id=None,
            reason=_REASON_INVALID_VIDEO,
        )

    reference_file, reference_angle = await _resolve_reference_image(
        session, shot=shot
    )

    # 即使没有 reference 也仍尝试抽帧 + embed，便于诊断（但最终 score=null）。
    video_path = tmp_dir / "shot_video.mp4"
    raw = await storage.download_file(key=video_file.storage_key)
    if not raw:
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=0,
            reference_view_angle=reference_angle.value if reference_angle else None,
            reference_file_id=reference_file.id if reference_file else None,
            reason=_REASON_INVALID_VIDEO,
        )
    video_path.write_bytes(raw)

    total_frames = await _probe_total_frames(input_path=video_path)
    plan = make_plan(
        input_path=video_path,
        output_pattern=tmp_dir / "frame_%d.jpg",
        total_frames=total_frames,
        target_count=target_count,
    )

    try:
        frame_paths = await _sample_frames(plan=plan)
    except RuntimeError as exc:
        logger.warning("ffmpeg sample failed for shot %s: %s", shot.id, exc)
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=0,
            reference_view_angle=reference_angle.value if reference_angle else None,
            reference_file_id=reference_file.id if reference_file else None,
            reason=_REASON_INVALID_VIDEO,
        )

    if not frame_paths:
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=0,
            reference_view_angle=reference_angle.value if reference_angle else None,
            reference_file_id=reference_file.id if reference_file else None,
            reason=_REASON_NO_FRAMES,
        )

    try:
        frame_vectors: list[list[float]] = []
        for path in frame_paths:
            frame_vectors.append(await _embed_image_file(client, image_path=path))
        shot_embedding = _average_embeddings(frame_vectors)
    except (Dinov2SidecarUnavailable, Dinov2SidecarError) as exc:
        logger.warning("dinov2 sidecar error for shot %s frames: %s", shot.id, exc)
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=len(frame_paths),
            reference_view_angle=reference_angle.value if reference_angle else None,
            reference_file_id=reference_file.id if reference_file else None,
            reason=_REASON_SIDECAR_UNAVAILABLE,
        )

    if reference_file is None:
        logger.warning(
            "shot %s has no reference ProductImage (front / three_quarter); score=null",
            shot.id,
        )
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=len(frame_paths),
            reference_view_angle=None,
            reference_file_id=None,
            reason=_REASON_NO_REFERENCE,
        )

    try:
        reference_vector = await _embed_storage_file(
            client, storage_key=reference_file.storage_key
        )
    except (Dinov2SidecarUnavailable, Dinov2SidecarError) as exc:
        logger.warning(
            "dinov2 sidecar error for shot %s reference: %s", shot.id, exc
        )
        return ConsistencyScoreResult(
            shot_id=shot.id,
            score=None,
            frame_count=len(frame_paths),
            reference_view_angle=reference_angle.value if reference_angle else None,
            reference_file_id=reference_file.id,
            reason=_REASON_SIDECAR_UNAVAILABLE,
        )

    score = _cosine(shot_embedding, reference_vector)
    return ConsistencyScoreResult(
        shot_id=shot.id,
        score=score,
        frame_count=len(frame_paths),
        reference_view_angle=reference_angle.value if reference_angle else None,
        reference_file_id=reference_file.id,
        reason=None,
    )


# --------------------------------------------------------------------------- #
# task_kind 入口
# --------------------------------------------------------------------------- #


async def run_shot_consistency_check_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """``shot_consistency_check`` 任务的 async runner。

    入参契约：
        - ``shot_id`` (``str``, required)
        - ``frame_count`` (``int``, optional, 默认 6)

    成功路径：
        把结果（即 :class:`ConsistencyScoreResult` 的 dump）写入
        :attr:`GenerationTask.result`，并把 ``score`` 同步到
        :attr:`Shot.consistency_score`（``score=None`` 时也会显式置空，
        便于前端区分"未跑"与"跑了但无结果"）。

    失败路径：
        任何阶段异常 → rollback 当前事务 → 独立会话写 failed +
        log_task_failure，与既有 worker 保持一致。
    """

    shot_id = (run_args.get("shot_id") or "").strip()
    if not shot_id:
        raise ValueError("shot_id is required for shot_consistency_check task")
    target_count = _coerce_target_count(run_args.get("frame_count"))

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 5)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running", shot_id=shot_id)

            shot = await _load_shot_or_raise(session, shot_id)

            tmp_dir = Path(tempfile.mkdtemp(prefix="dinov2_consistency_"))
            try:
                async with build_default_dinov2_client() as client:
                    result = await _compute_consistency_score(
                        session=session,
                        shot=shot,
                        client=client,
                        tmp_dir=tmp_dir,
                        target_count=target_count,
                    )
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            shot.consistency_score = result.score
            await session.flush()
            await store.set_progress(task_id, 90)

            await store.set_result(task_id, result.model_dump())
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                shot_id=shot_id,
                score=result.score,
                frame_count=result.frame_count,
                reason=result.reason,
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as fallback_session:
                fail_store = SqlAlchemyTaskStore(fallback_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await fallback_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))


def _coerce_target_count(raw: Any) -> int:
    """归一 frame_count 入参，缺省回退 ``DEFAULT_FRAME_COUNT``。"""

    if raw in (None, ""):
        return DEFAULT_FRAME_COUNT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_FRAME_COUNT
    if value <= 0:
        return DEFAULT_FRAME_COUNT
    # 上限保护：避免恶意调用方传 1e6 把 sidecar 打爆。
    return min(value, 64)


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "run_shot_consistency_check_task",
    # 暴露内部步骤，便于单测做白盒验证。
    "_average_embeddings",
    "_compute_consistency_score",
    "_cosine",
    "_resolve_reference_image",
]
