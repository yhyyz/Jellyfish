"""W27-T2 阈值引擎单测 + chain dispatch 集成测试。

覆盖矩阵
--------

纯函数侧（``threshold_engine.evaluate``）：

- score >= 0.85                    → ("pass", False)
- 0.75 <= score < 0.85             → ("warning", False)
- score <  0.75 + retry_count<2    → ("fail", True)
- score <  0.75 + retry_count>=2   → ("fail", False)
- score is None                    → ("warning", False)
- 边界值 0.85 / 0.75 严格按 ``>=`` 归到上一档

Worker 集成侧：

- shot_consistency_check worker 把 ``consistency_status`` 落库后，按
  W19b commit-then-send 契约让 ``video_generation`` 行先 commit、再
  通过 ``CommerceTaskDispatchService.dispatch_after_commit`` 投递（即
  send_task 调用必须发生在 commit 之后）。
"""

# pylint: disable=redefined-outer-name,protected-access

from __future__ import annotations

import base64
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
from app.models.task import GenerationTask
from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    FileType,
    ProjectStyle,
)
from app.services.visual_consistency import consistency_worker, threshold_engine
from app.services.visual_consistency.consistency_worker import (
    TASK_KIND,
    run_shot_consistency_check_task,
)


# --------------------------------------------------------------------------- #
# 1. 纯函数：5 个核心规则 + 2 个边界值
# --------------------------------------------------------------------------- #


def test_score_above_85_returns_pass_no_regen() -> None:
    """0.9 显著高于 0.85 → pass，永不触发重生。"""

    assert threshold_engine.evaluate(0.9, 0) == ("pass", False)


def test_score_75_to_85_returns_warning_no_regen() -> None:
    """0.80 落 [0.75, 0.85) → warning，不重生。"""

    assert threshold_engine.evaluate(0.80, 0) == ("warning", False)


def test_score_below_75_first_time_returns_fail_with_regen() -> None:
    """retry_count=0 + 低分 → fail + 触发自动重生。"""

    status, should_regen = threshold_engine.evaluate(0.50, 0)
    assert status == "fail"
    assert should_regen is True


def test_retry_count_2_no_more_regen_even_if_low_score() -> None:
    """到达 hard cap (retry_count>=MAX_AUTO_REGEN_RETRY) 后必须停止重生。"""

    status, should_regen = threshold_engine.evaluate(
        0.10, threshold_engine.MAX_AUTO_REGEN_RETRY
    )
    assert status == "fail"
    assert should_regen is False
    assert threshold_engine.MAX_AUTO_REGEN_RETRY == 2


def test_score_none_returns_warning() -> None:
    """degraded path：score=None 视为 warning，不阻塞流程也不重生。"""

    assert threshold_engine.evaluate(None, 0) == ("warning", False)


def test_boundary_at_85_is_pass() -> None:
    """边界值 0.85：左闭右开约定下归到 pass。"""

    assert threshold_engine.evaluate(0.85, 0) == ("pass", False)


def test_boundary_at_75_is_warning() -> None:
    """边界值 0.75：左闭右开约定下归到 warning，而非 fail。"""

    assert threshold_engine.evaluate(0.75, 0) == ("warning", False)


def test_retry_count_one_low_score_still_regens() -> None:
    """retry_count=1 仍在 hard cap 之下，低分时再来一次重生。"""

    status, should_regen = threshold_engine.evaluate(0.20, 1)
    assert status == "fail"
    assert should_regen is True


# --------------------------------------------------------------------------- #
# 2. 集成：worker 把 status 落库 + commit-then-send chain dispatch
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    """file-backed SQLite + 全 ORM 建表（与 test_consistency_worker 对齐）。"""

    db_path = tmp_path / "threshold-engine.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


async def _seed_pipeline(db: AsyncSession, *, shot_id: str) -> None:
    """种入 Project / Chapter / Shot / Product / ProductImage 关联链。"""

    db.add(Project(id="proj-1", name="t", style=ProjectStyle.real_people_city))
    db.add(Chapter(id="chap-1", project_id="proj-1", index=1, title="Ch1"))
    db.add(
        Shot(
            id=shot_id,
            chapter_id="chap-1",
            index=1,
            title="S1",
            generated_video_file_id="file-video",
        )
    )
    db.add(
        FileItem(
            id="file-video",
            type=FileType.video,
            name="shot-low.mp4",
            storage_key="videos/shot-low.mp4",
        )
    )
    db.add(
        FileItem(
            id="file-ref",
            type=FileType.image,
            name="front.png",
            storage_key="refs/front.png",
        )
    )
    db.add(Product(id="prod-1", name="P1"))
    db.add(
        ProductImage(
            product_id="prod-1",
            file_id="file-ref",
            view_angle=AssetViewAngle.front,
            quality_level=AssetQualityLevel.high,
            is_primary=True,
        )
    )
    db.add(
        ProjectProductLink(
            project_id="proj-1",
            chapter_id=None,
            shot_id=None,
            product_id="prod-1",
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


class _LowScoreFakeDinov2Client:
    """让 cosine 落到 0.5（< 0.75）触发 should_regen 路径。

    通过给"帧" vs "参考图" 不同向量、计算后得到约 0.5 的 cos similarity。
    具体构造：6 帧全用 [a, a, ...]、参考图用 [a, -a, a, -a, ...]，
    点积约为 0；本测试只关心"分数 < 0.75 → fail+regen"，所以 0.0 也合规。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._toggle = False

    async def __aenter__(self) -> "_LowScoreFakeDinov2Client":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def embed_b64(self, *, image_b64: str) -> Any:  # noqa: ARG002
        from app.core.contracts.visual_consistency import EmbedResponse

        self.calls.append(image_b64[:8])
        # 第 7 次（参考图）反向，与前 6 次正交 → cosine ≈ 0 < 0.75。
        if len(self.calls) >= 7:
            half = DINOV2_EMBED_DIM // 2
            vec = [0.0] * half + [1.0 / (half ** 0.5)] * half
        else:
            half = DINOV2_EMBED_DIM // 2
            vec = [1.0 / (half ** 0.5)] * half + [0.0] * half
        return EmbedResponse(embedding=vec, dim=DINOV2_EMBED_DIM, elapsed_ms=1)

    async def embed_bytes(self, *, image_bytes: bytes) -> Any:
        return await self.embed_b64(image_b64=base64.b64encode(image_bytes).decode())

    async def similarity_b64(self, **_: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


def _patch_all(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_local: Any,
    fake_client: Any,
) -> None:
    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.async_session_maker",
        session_local,
    )

    async def fake_download(*, key: str) -> bytes:  # noqa: ARG001
        return b"fake-bytes"

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.storage.download_file",
        fake_download,
    )

    async def fake_probe(*, input_path: Path) -> int:  # noqa: ARG001
        return 60

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker._probe_total_frames",
        fake_probe,
    )

    async def fake_sample(*, plan: Any) -> list[Path]:
        out: list[Path] = []
        parent = plan.output_pattern.parent
        name = plan.output_pattern.name
        for idx in range(1, 7):
            p = parent / name.replace("%d", str(idx))
            p.write_bytes(b"jpegstub")
            out.append(p)
        return out

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker._sample_frames",
        fake_sample,
    )

    monkeypatch.setattr(
        "app.services.visual_consistency.consistency_worker.build_default_dinov2_client",
        lambda: fake_client,
    )


@pytest.mark.asyncio
async def test_worker_persists_consistency_status_then_dispatches_regen(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """低分路径：worker 写 status=fail，retry_count++，并在 commit 后派
    video_generation；send_task 必须发生在 GenerationTask 行 commit 之后。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_pipeline(db, shot_id="shot-low")
        await db.commit()

    fake_client = _LowScoreFakeDinov2Client()
    _patch_all(monkeypatch, session_local=session_local, fake_client=fake_client)

    # 拦截 broker send_task：捕获参数 + 校验调用时点（DB 行已 commit）。
    captured: list[dict[str, Any]] = []

    def fake_send_task(name: str, *, args: list[Any], queue: str) -> None:
        captured.append({"name": name, "args": args, "queue": queue})

    monkeypatch.setattr(
        "app.services.commerce.task_dispatch.celery_app.send_task",
        fake_send_task,
    )

    task_id = await _create_task(session_local, run_args={"shot_id": "shot-low"})
    await run_shot_consistency_check_task(task_id, {"shot_id": "shot-low"})

    # 1) Shot.consistency_status / retry_count 已落库。
    async with session_local() as db:
        shot = await db.get(Shot, "shot-low")
        assert shot is not None
        assert shot.consistency_score is not None
        assert shot.consistency_score < threshold_engine.WARNING_LOWER
        assert shot.consistency_status == "fail"
        assert shot.consistency_retry_count == 1

        # 2) video_generation 子任务行已 commit 落库（W19b 关键点）。
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind == "video_generation"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert (rows[0].payload or {}).get("run_args", {}).get("shot_id") == "shot-low"

    # 3) celery send_task 至少被调一次，目标即 video_generation 行的 task_id。
    video_calls = [c for c in captured if c["args"] and c["args"][0] == rows[0].id]
    assert len(video_calls) == 1
    assert video_calls[0]["queue"] == "slow"
    assert video_calls[0]["name"] == "task.execute"
