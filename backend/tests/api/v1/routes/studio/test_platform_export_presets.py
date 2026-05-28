"""``/api/v1/studio/platform-export-presets`` 接口测试（W23-T1，P4 Wave A）。

P4 Wave A 引入"多平台导出预设"基础设施，本测试集覆盖 6 类用例：

1. ``test_list_returns_five_system_presets``：bootstrap 后列表返回 5 条
   ``is_system=True`` 系统预设；按 ``is_system DESC`` + ``sort_order``
   排序。
2. ``test_list_filters_by_platform``：``?platform=tiktok`` 只返回
   tiktok_default。
3. ``test_create_user_preset_returns_201``：合法 payload 创建用户态预设，
   ``is_system`` 强制为 False，id 缺省自动生成。
4. ``test_patch_partial_update_user_preset``：PATCH 仅修改部分字段，其它
   字段保留原值；``is_system`` 不被改写。
5. ``test_delete_user_preset_succeeds``：用户预设可以删除；删除后再次
   GET 详情返回 404。
6. ``test_delete_system_preset_rejected_400``：系统预设删除请求强制返回
   400，且 DB 行仍然存在（保护契约）。

test fixture 仿照 ``test_outcomes_crud.py`` 模式：内存 SQLite + override
``get_db`` + 跑 bootstrap_platform_export_presets seed 5 行。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.platform_export_preset  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.subtitle  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.platform_export_preset import PlatformExportPreset
from app.services.commerce.bootstrap_export_presets import (
    bootstrap_platform_export_presets,
)


_EXPECTED_TOTAL = 5

_ENDPOINT = "/api/v1/studio/platform-export-presets"


async def _build_engine_with_seed() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构建一次性 SQLite engine 并 bootstrap 5 个系统预设。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        await bootstrap_platform_export_presets(session)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """复用 ``get_db`` 的 commit/rollback 语义，确保 PATCH/DELETE 真正落库。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _user_payload(**overrides: object) -> dict[str, object]:
    """组装一个最小可用的用户态预设 POST body。"""

    base: dict[str, object] = {
        "name": "测试自定义预设",
        "platform": "douyin",
        "aspect_ratio": "9:16",
        "max_duration_sec": 30,
        "file_format": "mp4",
        "codec_preset": "h264_high_4_1",
        "loudness_lufs": -16.0,
        "sort_order": 100,
        "description": "用户态预设示例",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_list_returns_five_system_presets(client: TestClient) -> None:
    """bootstrap 后列表返回 5 条系统预设，全部 ``is_system=True``。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(_ENDPOINT)
        assert res.status_code == 200, res.text
        items = res.json()["data"]
        assert len(items) == _EXPECTED_TOTAL
        assert all(it["is_system"] is True for it in items)
        # 排序：sort_order ASC（同档位 name ASC）
        sort_orders = [it["sort_order"] for it in items]
        assert sort_orders == sorted(sort_orders), (
            f"sort_order 未升序：{sort_orders}"
        )
        ids = {it["id"] for it in items}
        assert ids == {
            "douyin_default",
            "kuaishou_default",
            "xiaohongshu_default",
            "youtube_shorts_default",
            "tiktok_default",
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_filters_by_platform(client: TestClient) -> None:
    """``?platform=tiktok`` 只返回 tiktok_default。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(_ENDPOINT, params={"platform": "tiktok"})
        assert res.status_code == 200, res.text
        items = res.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == "tiktok_default"
        assert items[0]["platform"] == "tiktok"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_preset_returns_201(client: TestClient) -> None:
    """合法 payload → 201；id 缺省由 service 生成；is_system 强制 False。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _user_payload(name="我的抖音预设")
        res = client.post(_ENDPOINT, json=body)
        assert res.status_code == 201, res.text
        data = res.json()["data"]
        assert isinstance(data["id"], str) and data["id"]
        assert data["is_system"] is False
        assert data["name"] == "我的抖音预设"
        assert data["platform"] == "douyin"
        assert data["max_duration_sec"] == 30

        # DB 上确实多了 1 行
        async with session_local() as session:
            rows = (
                await session.execute(select(PlatformExportPreset))
            ).scalars().all()
            assert len(rows) == _EXPECTED_TOTAL + 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_partial_update_user_preset(client: TestClient) -> None:
    """PATCH 仅修改 name / max_duration_sec，其它字段保留原值；``is_system`` 不变。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        # 先创建一条用户预设
        create = client.post(_ENDPOINT, json=_user_payload(name="原始名称"))
        assert create.status_code == 201, create.text
        preset_id = create.json()["data"]["id"]

        res = client.patch(
            f"{_ENDPOINT}/{preset_id}",
            json={"name": "改名后", "max_duration_sec": 45},
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["name"] == "改名后"
        assert data["max_duration_sec"] == 45
        assert data["aspect_ratio"] == "9:16"  # 未传保持原值
        assert data["is_system"] is False
        assert data["codec_preset"] == "h264_high_4_1"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_user_preset_succeeds(client: TestClient) -> None:
    """用户预设删除后 GET 详情应返回 404。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        create = client.post(_ENDPOINT, json=_user_payload(name="待删除预设"))
        assert create.status_code == 201, create.text
        preset_id = create.json()["data"]["id"]

        delete = client.delete(f"{_ENDPOINT}/{preset_id}")
        assert delete.status_code == 204, delete.text

        detail = client.get(f"{_ENDPOINT}/{preset_id}")
        assert detail.status_code == 404, detail.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_system_preset_rejected_400(client: TestClient) -> None:
    """系统预设删除请求 → 400，且 DB 行仍然存在。"""

    session_local, engine = await _build_engine_with_seed()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        delete = client.delete(f"{_ENDPOINT}/douyin_default")
        assert delete.status_code == 400, delete.text

        # DB 行仍在
        async with session_local() as session:
            row = await session.get(PlatformExportPreset, "douyin_default")
            assert row is not None
            assert row.is_system is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
