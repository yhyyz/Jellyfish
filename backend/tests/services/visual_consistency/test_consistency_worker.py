"""``shot_consistency_check`` worker 单测（W27-T1）。

测试策略：
    - 用 file-backed SQLite + ``Base.metadata.create_all`` 起完整 ORM；
    - 把 worker 内部的 ``async_session_maker`` monkeypatch 到测试 session_local；
    - 把 ``ffprobe / ffmpeg`` 子进程封装替换为返回固定结果的 stub，
      避免依赖系统二进制；
    - 把 :class:`Dinov2HttpClient` 替换为返回固定 embedding 的 fake，
      不发起真实网络请求；
    - 把 ``app.core.storage.download_file`` 替换为返回任意非空 bytes 的 stub，
      避免依赖 minio。
"""

# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.contracts.visual_consistency import DINOV2_EMBED_DIM
from app.core.db import Base
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import DeliveryMode
from app.models.commerce_assets import Product, ProductImage, ProjectProductLink
from app.models.studio import Chapter, FileItem, Project, Shot
from app.models.studio_shots import ShotStatus
from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    FileType,
    ProjectStyle,
)
from app.services.visual_consistency import consistency_worker
from app.services.visual_consistency.consistency_worker import (
    TASK_KIND,
    _average_embeddings,
    _cosine,
    run_shot_consistency_check_task,
)


# --------------------------------------------------------------------------- #
# Fixtures: SQLite + 种子数据
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    """file-backed SQLite + 全表建表，与 test_compliance_check_worker 一致。"""

    db_path = tmp_path / "consistency-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


async def _seed_full_pipeline(
    db: AsyncSession,
    *,
    shot_id: str = "shot-1",
    with_reference: bool = True,
) -> None:
    """种入 Project / Chapter / Shot / Product / ProductImage 关联链。"""

    db.add(
        Project(id="proj-1", name="测试项目", style=ProjectStyle.real_people_city)
    )
    db.add(Chapter(id="chap-1", project_id="proj-1", index=1, title="Ch1"))
    db.add(
        FileItem(
            id="vid-file-1",
            type=FileType.video,
            name="shot.mp4",
            storage_key="videos/shot.mp4",
        )
    )
    db.add(
        Shot(
            id=shot_id,
            chapter_id="chap-1",
            index=1,
            title="测试镜头",
            status=ShotStatus.ready,
            script_excerpt="",
            dubbed_video_file_id="vid-file-1",
        )
    )
    db.add(Product(id="prod-1", name="测试商品"))
    db.add(
        ProjectProductLink(
            project_id="proj-1",
            chapter_id=None,
            shot_id=None,
            product_id="prod-1",
        )
    )
    if with_reference:
        db.add(
            FileItem(
                id="ref-file-1",
                type=FileType.image,
                name="ref.jpg",
                storage_key="images/ref.jpg",
            )
        )
        db.add(
            ProductImage(
                product_id="prod-1",
                file_id="ref-file-1",
                quality_level=AssetQualityLevel.high,
                view_angle=AssetViewAngle.front,
                is_primary=True,
            )
        )
    await db.flush()


async def _create_task(session_local: Any, *, run_args: dict[str, Any]) -> str:
    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": TASK_KIND, "run_args": run_args},
            mode=DeliveryMode.async_polling,
            task_kind=TASK_KIND,
        )
        await db.commit()
        return task.id


# --------------------------------------------------------------------------- #
# Stubs：ffmpeg / ffprobe / storage / Dinov2HttpClient
# --------------------------------------------------------------------------- #


class _FakeDinov2Client:
    """伪客户端：每次 embed_b64 / embed_bytes 返回固定向量。

    构造时传入 dict[str, list[float]]，按 base64 字符串前缀路由不同向量；
    缺省走 ``default_vec``。便于在单测中区分"帧 vs 参考图"。
    """

    def __init__(
        self,
        *,
        default_vec: list[float] | None = None,
        route: dict[str, list[float]] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self._default = default_vec or [1.0 / (DINOV2_EMBED_DIM ** 0.5)] * DINOV2_EMBED_DIM
        self._route = route or {}
        self._raise_on = raise_on
        self.calls: list[str] = []

    async def __aenter__(self) -> "_FakeDinov2Client":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def embed_b64(self, *, image_b64: str) -> Any:
        self.calls.append(image_b64[:8])
        if self._raise_on is not None and (
            self._raise_on == "*" or image_b64.startswith(self._raise_on)
        ):
            from app.core.integrations.dinov2.client import Dinov2SidecarUnavailable

            raise Dinov2SidecarUnavailable("simulated sidecar down")
        vec = self._route.get(image_b64[:8], self._default)
        from app.core.contracts.visual_consistency import EmbedResponse

        return EmbedResponse(embedding=vec, dim=DINOV2_EMBED_DIM, elapsed_ms=1)

    async def embed_bytes(self, *, image_bytes: bytes) -> Any:
        import base64

        return await self.embed_b64(image_b64=base64.b64encode(image_bytes).decode())

    async def similarity_b64(self, **_: Any) -> Any:  # pragma: no cover - 未用
        raise NotImplementedError


def _patch_session_maker(monkeypatch: pytest.MonkeyPatch, session_local: Any) -> None:
    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.async_session_maker",
        session_local,
    )


def _patch_storage_download(
    monkeypatch: pytest.MonkeyPatch, payload: bytes = b"\x00\x01\x02"
) -> None:
    """让 storage.download_file 返回固定字节，避免连 minio。"""

    async def fake_download(*, key: str) -> bytes:  # noqa: ARG001
        return payload

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.storage.download_file",
        fake_download,
    )


def _patch_ffprobe(monkeypatch: pytest.MonkeyPatch, *, total_frames: int = 120) -> None:
    async def fake_probe(*, input_path: Path) -> int:  # noqa: ARG001
        return total_frames

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker._probe_total_frames",
        fake_probe,
    )


def _patch_ffmpeg_sample(
    monkeypatch: pytest.MonkeyPatch, *, frame_count: int = 6
) -> None:
    """让 _sample_frames 返回 frame_count 个真实存在的小文件。"""

    async def fake_sample(*, plan: Any) -> list[Path]:
        parent = plan.output_pattern.parent
        pattern_name = plan.output_pattern.name
        out: list[Path] = []
        for idx in range(1, frame_count + 1):
            p = parent / pattern_name.replace("%d", str(idx))
            p.write_bytes(b"jpegstub")
            out.append(p)
        return out

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker._sample_frames",
        fake_sample,
    )


def _patch_default_client_factory(
    monkeypatch: pytest.MonkeyPatch, fake_client: _FakeDinov2Client
) -> None:
    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.build_default_dinov2_client",
        lambda: fake_client,
    )


# --------------------------------------------------------------------------- #
# 1. 纯函数：_average_embeddings / _cosine
# --------------------------------------------------------------------------- #


def test_average_embeddings_l2_normalizes() -> None:
    vec_a = [1.0, 0.0] + [0.0] * (DINOV2_EMBED_DIM - 2)
    vec_b = [0.0, 1.0] + [0.0] * (DINOV2_EMBED_DIM - 2)
    avg = _average_embeddings([vec_a, vec_b])
    norm = sum(v * v for v in avg) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_cosine_returns_one_for_identical_unit_vector() -> None:
    vec = [1.0 / (DINOV2_EMBED_DIM ** 0.5)] * DINOV2_EMBED_DIM
    assert _cosine(vec, vec) == pytest.approx(1.0, abs=1e-5)


def test_cosine_returns_zero_for_zero_vector() -> None:
    vec_zero = [0.0] * DINOV2_EMBED_DIM
    vec_unit = [1.0 / (DINOV2_EMBED_DIM ** 0.5)] * DINOV2_EMBED_DIM
    assert _cosine(vec_zero, vec_unit) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# 2. happy path：抽帧 → embed → cosine → 写库
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_runner_writes_consistency_score_when_reference_exists(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = session_factory
    async with session_local() as db:
        await _seed_full_pipeline(db, shot_id="shot-happy", with_reference=True)
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_storage_download(monkeypatch, b"video-or-image-bytes")
    _patch_ffprobe(monkeypatch, total_frames=120)
    _patch_ffmpeg_sample(monkeypatch, frame_count=6)

    fake_client = _FakeDinov2Client()
    _patch_default_client_factory(monkeypatch, fake_client)

    task_id = await _create_task(session_local, run_args={"shot_id": "shot-happy"})
    await run_shot_consistency_check_task(task_id, {"shot_id": "shot-happy"})

    # 6 帧 + 1 参考 = 7 次 embed 调用。
    assert len(fake_client.calls) == 7

    async with session_local() as db:
        shot = await db.get(Shot, "shot-happy")
        assert shot is not None
        assert shot.consistency_score is not None
        assert shot.consistency_score == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_runner_writes_null_when_no_reference(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = session_factory
    async with session_local() as db:
        await _seed_full_pipeline(db, shot_id="shot-no-ref", with_reference=False)
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_storage_download(monkeypatch, b"video-bytes")
    _patch_ffprobe(monkeypatch, total_frames=60)
    _patch_ffmpeg_sample(monkeypatch, frame_count=3)

    fake_client = _FakeDinov2Client()
    _patch_default_client_factory(monkeypatch, fake_client)

    task_id = await _create_task(session_local, run_args={"shot_id": "shot-no-ref"})
    await run_shot_consistency_check_task(task_id, {"shot_id": "shot-no-ref"})

    async with session_local() as db:
        shot = await db.get(Shot, "shot-no-ref")
        assert shot is not None
        assert shot.consistency_score is None

        from app.models.task import GenerationTask

        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.result is not None
        assert task.result.get("score") is None
        assert task.result.get("reason") == "no_reference"
        assert task.result.get("frame_count") == 3


@pytest.mark.asyncio
async def test_runner_writes_null_when_sidecar_unavailable(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = session_factory
    async with session_local() as db:
        await _seed_full_pipeline(db, shot_id="shot-down", with_reference=True)
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_storage_download(monkeypatch, b"bytes")
    _patch_ffprobe(monkeypatch, total_frames=60)
    _patch_ffmpeg_sample(monkeypatch, frame_count=2)

    # 任意 b64 都触发 503 → 应被 worker 包成 reason=sidecar_unavailable。
    fake_client = _FakeDinov2Client(raise_on="*")
    _patch_default_client_factory(monkeypatch, fake_client)

    task_id = await _create_task(session_local, run_args={"shot_id": "shot-down"})
    await run_shot_consistency_check_task(task_id, {"shot_id": "shot-down"})

    async with session_local() as db:
        shot = await db.get(Shot, "shot-down")
        assert shot is not None
        assert shot.consistency_score is None

        from app.models.task import GenerationTask

        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.result is not None
        assert task.result.get("reason") == "sidecar_unavailable"


@pytest.mark.asyncio
async def test_runner_falls_back_to_three_quarter_when_front_missing(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = session_factory
    async with session_local() as db:
        # 种 product 但只有 three_quarter 视角图。
        db.add(
            Project(id="proj-1", name="t", style=ProjectStyle.real_people_city)
        )
        db.add(Chapter(id="chap-1", project_id="proj-1", index=1, title="C"))
        db.add(
            FileItem(
                id="vid-file-1",
                type=FileType.video,
                name="v.mp4",
                storage_key="v.mp4",
            )
        )
        db.add(
            Shot(
                id="shot-tq",
                chapter_id="chap-1",
                index=1,
                title="t",
                status=ShotStatus.ready,
                script_excerpt="",
                dubbed_video_file_id="vid-file-1",
            )
        )
        db.add(Product(id="prod-1", name="p"))
        db.add(
            ProjectProductLink(
                project_id="proj-1",
                chapter_id=None,
                shot_id=None,
                product_id="prod-1",
            )
        )
        db.add(
            FileItem(
                id="ref-tq",
                type=FileType.image,
                name="ref.jpg",
                storage_key="ref-tq.jpg",
            )
        )
        db.add(
            ProductImage(
                product_id="prod-1",
                file_id="ref-tq",
                quality_level=AssetQualityLevel.high,
                view_angle=AssetViewAngle.three_quarter,
                is_primary=True,
            )
        )
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_storage_download(monkeypatch, b"bytes")
    _patch_ffprobe(monkeypatch, total_frames=60)
    _patch_ffmpeg_sample(monkeypatch, frame_count=2)
    _patch_default_client_factory(monkeypatch, _FakeDinov2Client())

    task_id = await _create_task(session_local, run_args={"shot_id": "shot-tq"})
    await run_shot_consistency_check_task(task_id, {"shot_id": "shot-tq"})

    async with session_local() as db:
        from app.models.task import GenerationTask

        task = await db.get(GenerationTask, task_id)
        assert task is not None and task.result is not None
        assert task.result.get("reference_view_angle") == "THREE_QUARTER"
        assert task.result.get("reference_file_id") == "ref-tq"


# --------------------------------------------------------------------------- #
# 3. registry 对接：task_kind 已在 task_executor_registry 注册
# --------------------------------------------------------------------------- #


def test_shot_consistency_check_registered_in_executor_registry() -> None:
    from app.services.worker.task_registry import task_executor_registry

    executor = task_executor_registry.resolve(TASK_KIND)
    assert executor is not None
    # 与 spec 一致：slow 队列、600s 超时（由 AbstractAsyncDelegatingExecutor 持有）。
    assert getattr(executor, "timeout_seconds", None) == consistency_worker.DEFAULT_TIMEOUT_SEC
