"""W31-T8 PATCH segment audio endpoint API 测试。

覆盖 8 个 case：
1. happy path：三字段都改 → 200 + 返回更新后的 ChapterTimelineSegmentRead。
2. 偏量改：只传 ``bgm_file_id`` 不动其他字段。
3. 显式传 null：``bgm_file_id=null`` 把 segment.bgm_file_id 设为 NULL（删
   关联），不影响 sfx/ducking。
4. ducking 越界（-100）→ 422。
5. ducking 越界（+5）→ 422。
6. segment 不存在 → 404。
7. segment 属于另一章节 → 404（防越权 PATCH）。
8. chapter 不存在 → 404。
"""

# pylint: disable=invalid-name,redefined-outer-name

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.routes.studio import chapters as chapters_route
from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio import (
    Chapter,
    ChapterTimelineSegment,
    FileItem,
    FileType,
    Project,
    ProjectStyle,
    Shot,
    ShotStatus,
)
from app.models.types import AudioStrategy


_PROJECT_ID = "proj-w31t8"
_CHAPTER_A = "chap-A"
_CHAPTER_B = "chap-B"
_SHOT_A = "shot-A"
_SHOT_B = "shot-B"
_SEG_A = "seg-A"
_SEG_B = "seg-B"


@pytest.fixture()
def session_local(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    """临时 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "patch-segment-audio.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    try:
        yield sm
    finally:

        async def _dispose() -> None:
            await engine.dispose()

        asyncio.run(_dispose())


def _seed(sm: async_sessionmaker[AsyncSession]) -> None:
    """种入 1 项目 + 2 章节 + 2 镜头 + 2 segment + 2 BGM 文件。

    seg-A 默认带 BGM=bgm-1，无 SFX，ducking_db=-12（默认）。
    seg-B 在另一章节，用于"跨 chapter 越权 PATCH 应 404"用例。
    """

    async def _go() -> None:
        async with sm() as db:
            db.add(
                Project(
                    id=_PROJECT_ID,
                    name="W31-T8",
                    style=ProjectStyle.real_people_city,
                )
            )
            db.add(
                Chapter(
                    id=_CHAPTER_A, project_id=_PROJECT_ID, index=0, title="chA"
                )
            )
            db.add(
                Chapter(
                    id=_CHAPTER_B, project_id=_PROJECT_ID, index=1, title="chB"
                )
            )
            for chap_id, shot_id in ((_CHAPTER_A, _SHOT_A), (_CHAPTER_B, _SHOT_B)):
                db.add(
                    Shot(
                        id=shot_id,
                        chapter_id=chap_id,
                        index=0,
                        title=f"shot-{shot_id}",
                        status=ShotStatus.ready,
                        audio_strategy=AudioStrategy.silent_with_tts,
                    )
                )
            db.add(
                FileItem(id="bgm-1", type=FileType.audio, name="bgm1.mp3",
                         storage_key="bgm/1.mp3")
            )
            db.add(
                FileItem(id="bgm-2", type=FileType.audio, name="bgm2.mp3",
                         storage_key="bgm/2.mp3")
            )
            db.add(
                FileItem(id="sfx-1", type=FileType.audio, name="sfx1.mp3",
                         storage_key="sfx/1.mp3")
            )
            db.add(
                ChapterTimelineSegment(
                    id=_SEG_A,
                    chapter_id=_CHAPTER_A,
                    shot_id=_SHOT_A,
                    position=0,
                    bgm_file_id="bgm-1",
                    sfx_file_id=None,
                    bgm_ducking_db=-12.0,
                )
            )
            db.add(
                ChapterTimelineSegment(
                    id=_SEG_B,
                    chapter_id=_CHAPTER_B,
                    shot_id=_SHOT_B,
                    position=0,
                    bgm_file_id=None,
                    sfx_file_id=None,
                    bgm_ducking_db=-12.0,
                )
            )
            await db.commit()

    asyncio.run(_go())


@pytest.fixture()
def client_with_db(
    session_local: async_sessionmaker[AsyncSession],
) -> Iterator[TestClient]:
    """给 TestClient 注入临时 DB；每个用例都种入相同 fixture 数据。"""

    _seed(session_local)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _read_segment(
    sm: async_sessionmaker[AsyncSession], segment_id: str
) -> dict[str, Any]:
    """直接读 segment 三字段用于 DB-level 断言。"""

    async def _go() -> dict[str, Any]:
        async with sm() as db:
            seg = await db.get(ChapterTimelineSegment, segment_id)
            assert seg is not None
            return {
                "bgm_file_id": seg.bgm_file_id,
                "sfx_file_id": seg.sfx_file_id,
                "bgm_ducking_db": float(seg.bgm_ducking_db),
            }

    return asyncio.run(_go())


_PATCH_PATH = "/api/v1/studio/chapters/{chapter_id}/timeline/segments/{segment_id}/audio"


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------


def test_patch_happy_path_updates_all_three_fields(
    client_with_db: TestClient, session_local: async_sessionmaker[AsyncSession]
) -> None:
    """三字段都改 → 200 + 响应体字段一致 + DB row 真改了。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={
            "bgm_file_id": "bgm-2",
            "sfx_file_id": "sfx-1",
            "bgm_ducking_db": -18.5,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["id"] == _SEG_A
    assert data["bgm_file_id"] == "bgm-2"
    assert data["sfx_file_id"] == "sfx-1"
    assert data["bgm_ducking_db"] == pytest.approx(-18.5)

    persisted = _read_segment(session_local, _SEG_A)
    assert persisted["bgm_file_id"] == "bgm-2"
    assert persisted["sfx_file_id"] == "sfx-1"
    assert persisted["bgm_ducking_db"] == pytest.approx(-18.5)


# ---------------------------------------------------------------------------
# 2. 偏量改：只传一个字段
# ---------------------------------------------------------------------------


def test_patch_partial_only_bgm_keeps_sfx_and_ducking(
    client_with_db: TestClient, session_local: async_sessionmaker[AsyncSession]
) -> None:
    """只传 bgm_file_id，sfx_file_id 与 bgm_ducking_db 保持原值。"""

    # 先把 fixture 改成 sfx=sfx-1, ducking=-15（确保有非默认基线）
    client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={"sfx_file_id": "sfx-1", "bgm_ducking_db": -15.0},
    )

    # 然后只动 bgm_file_id
    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={"bgm_file_id": "bgm-2"},
    )
    assert res.status_code == 200

    persisted = _read_segment(session_local, _SEG_A)
    assert persisted["bgm_file_id"] == "bgm-2"
    assert persisted["sfx_file_id"] == "sfx-1"
    assert persisted["bgm_ducking_db"] == pytest.approx(-15.0)


# ---------------------------------------------------------------------------
# 3. 显式 null：清空 BGM 关联
# ---------------------------------------------------------------------------


def test_patch_explicit_null_clears_bgm(
    client_with_db: TestClient, session_local: async_sessionmaker[AsyncSession]
) -> None:
    """``bgm_file_id=null`` 把 DB 列写 NULL；其它字段不变。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={"bgm_file_id": None},
    )
    assert res.status_code == 200
    persisted = _read_segment(session_local, _SEG_A)
    assert persisted["bgm_file_id"] is None
    assert persisted["bgm_ducking_db"] == pytest.approx(-12.0)


# ---------------------------------------------------------------------------
# 4 & 5. ducking 越界
# ---------------------------------------------------------------------------


def test_patch_ducking_below_minus_30_returns_422(client_with_db: TestClient) -> None:
    """``bgm_ducking_db=-100`` 触发 Pydantic 422。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={"bgm_ducking_db": -100.0},
    )
    assert res.status_code == 422


def test_patch_ducking_above_zero_returns_422(client_with_db: TestClient) -> None:
    """``bgm_ducking_db=+5`` 触发 Pydantic 422。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_A),
        json={"bgm_ducking_db": 5.0},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 6. segment 不存在
# ---------------------------------------------------------------------------


def test_patch_unknown_segment_returns_404(client_with_db: TestClient) -> None:
    """segment_id 不存在 → 404。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id="ghost"),
        json={"bgm_file_id": "bgm-1"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 7. 跨 chapter 越权（segment 属于 chapter B 但路径写 A）
# ---------------------------------------------------------------------------


def test_patch_segment_belongs_to_other_chapter_returns_404(
    client_with_db: TestClient,
) -> None:
    """seg-B 属于 chapter B，但路径用 chapter A → 404 防越权。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id=_CHAPTER_A, segment_id=_SEG_B),
        json={"bgm_file_id": "bgm-1"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 8. chapter 不存在
# ---------------------------------------------------------------------------


def test_patch_unknown_chapter_returns_404(client_with_db: TestClient) -> None:
    """chapter_id 不存在 → 404（``get_or_404`` 兜底）。"""

    res = client_with_db.patch(
        _PATCH_PATH.format(chapter_id="ghost", segment_id=_SEG_A),
        json={"bgm_file_id": "bgm-1"},
    )
    assert res.status_code == 404
