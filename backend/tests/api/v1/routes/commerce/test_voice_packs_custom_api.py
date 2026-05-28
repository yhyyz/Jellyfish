"""``/api/v1/commerce/voice-packs/custom`` 4 endpoints 路由测试（W29-T6）。

覆盖：
    1. POST happy path：上传合规 wav 文件 → 202 Accepted + voice_pack_id；
       下游 DashScope SDK 被调用一次；DB 行落地为 deploying 状态。
    2. POST 拒绝路径：bad prefix / bad target_model / 非法格式 → 400 / 422。
    3. POST oversize：>10MB 上传 → 413。
    4. GET status：deploying / ready / failed 三态正确映射 + failure_reason 解析。
    5. GET list：按 clone_status 过滤 + 分页字段齐全。
    6. DELETE happy path：voice_pack 标 deleted；DashScope delete_voice 被调。
    7. DELETE 系统行：禁止删除 → 403。
    8. DELETE 不存在 → 404。
"""

# pylint: disable=invalid-name,redefined-outer-name,too-few-public-methods,protected-access

from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
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
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.types import (
    VoiceCloneStatus,
    VoiceGender,
    VoiceProvider,
    VoiceRegion,
)
from app.models.voice_pack import VoicePack
from app.services.studio import voice_clone_service


# ---------------------------------------------------------------------------
# DashScope SDK + storage 替身
# ---------------------------------------------------------------------------


class _FakeVoiceEnrollmentService:
    """与 service 测试同样的替身；记录 create / query / delete 调用。"""

    create_calls: list[dict[str, Any]] = []
    query_calls: list[str] = []
    delete_calls: list[str] = []
    _create_returns: str = "cosyvoice-v3.5-plus-myvoice-fakehash"
    _query_returns: dict[str, Any] = {"status": "DEPLOYING"}
    _delete_should_raise: bool = False

    def create_voice(self, **kwargs: Any) -> str:
        self.create_calls.append(kwargs)
        return self._create_returns

    def query_voice(self, voice_id: str) -> dict[str, Any]:
        self.query_calls.append(voice_id)
        return self._query_returns

    def delete_voice(self, voice_id: str) -> None:
        self.delete_calls.append(voice_id)
        if self._delete_should_raise:
            raise RuntimeError("voice not found")


class _FakeStoredFileInfo:
    """:class:`storage.StoredFileInfo` 的最简替身，仅含 key + url。"""

    def __init__(self, key: str, url: str) -> None:
        self.key = key
        self.url = url


@pytest.fixture(autouse=True)
def _patch_dashscope_and_storage(monkeypatch):
    """全局替换 DashScope SDK + storage.upload_file，避免真实调用。"""
    _FakeVoiceEnrollmentService.create_calls = []
    _FakeVoiceEnrollmentService.query_calls = []
    _FakeVoiceEnrollmentService.delete_calls = []
    _FakeVoiceEnrollmentService._create_returns = (
        "cosyvoice-v3.5-plus-myvoice-fakehash"
    )
    _FakeVoiceEnrollmentService._query_returns = {"status": "DEPLOYING"}
    _FakeVoiceEnrollmentService._delete_should_raise = False
    monkeypatch.setattr(
        voice_clone_service, "VoiceEnrollmentService", _FakeVoiceEnrollmentService
    )

    async def _fake_upload(
        *, key: str, data, content_type=None, extra_args=None
    ):
        return _FakeStoredFileInfo(key=key, url=f"https://oss.example/{key}")

    monkeypatch.setattr(
        voice_clone_service.storage, "upload_file", _fake_upload
    )
    yield


# ---------------------------------------------------------------------------
# DB 引擎 + dependency override
# ---------------------------------------------------------------------------


async def _build_engine() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构建 in-memory SQLite + 全 schema。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """同步 outcomes 测试的 commit/rollback 语义。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _make_wav_bytes(
    *,
    duration_sec: float = 15.0,
    sample_rate_hz: int = 16000,
    channels: int = 1,
) -> bytes:
    """生成静音 WAV，与 voice_clone_service 测试同样的工具。"""
    frame_count = int(sample_rate_hz * duration_sec)
    if channels == 1:
        samples = np.zeros(frame_count, dtype=np.float32)
    else:
        samples = np.zeros((frame_count, channels), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate_hz, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# POST happy path + 拒绝路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_creates_voice_pack_returns_202(
    client: TestClient,
) -> None:
    """合规 wav + 合规 form fields → 202 Accepted + voice_pack_id 落地。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        wav = _make_wav_bytes()
        res = client.post(
            "/api/v1/commerce/voice-packs/custom",
            files={"sample_file": ("voice.wav", wav, "audio/wav")},
            data={
                "prefix": "myvoice",
                "target_model": "cosyvoice-v3.5-plus",
                "region": "cn-beijing",
                "display_name": "测试克隆音色",
                "language_hints": "zh",
            },
        )
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["data"]["voice_pack_id"].startswith("clone_")
        assert body["data"]["clone_status"] == "deploying"

        # DashScope create_voice 必被调用一次
        assert len(_FakeVoiceEnrollmentService.create_calls) == 1
        call = _FakeVoiceEnrollmentService.create_calls[0]
        assert call["target_model"] == "cosyvoice-v3.5-plus"
        assert call["prefix"] == "myvoice"

        # DB 行落地
        async with session_local() as session:
            voice_pack = await session.get(
                VoicePack, body["data"]["voice_pack_id"]
            )
            assert voice_pack is not None
            assert voice_pack.is_system is False
            assert voice_pack.target_model == "cosyvoice-v3.5-plus"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_rejects_invalid_prefix_with_422(
    client: TestClient,
) -> None:
    """prefix 含特殊字符 → 422（CustomVoiceCreateRequest validator）。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        wav = _make_wav_bytes()
        res = client.post(
            "/api/v1/commerce/voice-packs/custom",
            files={"sample_file": ("voice.wav", wav, "audio/wav")},
            data={
                "prefix": "my-voice",
                "target_model": "cosyvoice-v3.5-plus",
                "region": "cn-beijing",
                "display_name": "x",
            },
        )
        assert res.status_code == 422, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_rejects_unparseable_audio_with_422(
    client: TestClient,
) -> None:
    """假装是 wav 但实际是垃圾 bytes → 422 audio metadata validation failed。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        junk = b"this is not wav at all"
        res = client.post(
            "/api/v1/commerce/voice-packs/custom",
            files={"sample_file": ("voice.wav", junk, "audio/wav")},
            data={
                "prefix": "myvoice",
                "target_model": "cosyvoice-v3.5-plus",
                "region": "cn-beijing",
                "display_name": "test",
            },
        )
        assert res.status_code == 422, res.text
        body = res.json()
        assert "audio metadata" in str(body)
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_rejects_oversized_file_with_413(
    client: TestClient,
) -> None:
    """>10 MB sample 文件 → 413。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        big = b"\x00" * (11 * 1024 * 1024)
        res = client.post(
            "/api/v1/commerce/voice-packs/custom",
            files={"sample_file": ("big.wav", big, "audio/wav")},
            data={
                "prefix": "myvoice",
                "target_model": "cosyvoice-v3.5-plus",
                "region": "cn-beijing",
                "display_name": "test",
            },
        )
        assert res.status_code == 413, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# GET status
# ---------------------------------------------------------------------------


async def _seed_voice_pack(
    session_local,
    *,
    voice_pack_id: str = "clone_status_test",
    clone_status: VoiceCloneStatus = VoiceCloneStatus.deploying,
    description: str = "",
    cloned_at: datetime | None = None,
    is_system: bool = False,
) -> None:
    """在 DB 里塞一条 VoicePack 行。"""
    async with session_local() as session:
        session.add(
            VoicePack(
                id=voice_pack_id,
                name="测试音色",
                provider=VoiceProvider.aliyun_cosyvoice,
                provider_voice_id="cosyvoice-v3.5-plus-myvoice-x",
                language_code="zh-CN",
                gender=VoiceGender.neutral,
                description=description,
                default_speed=1.0,
                is_system=is_system,
                sort_order=1000,
                target_model="cosyvoice-v3.5-plus",
                region=VoiceRegion.cn_beijing,
                clone_status=clone_status,
                sample_audio_oss_key="voice-clone-samples/test.wav",
                cloned_at=cloned_at,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_status_returns_deploying(client: TestClient) -> None:
    """deploying 行 → 200 + clone_status=deploying。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/voice-packs/custom/clone_status_test/status"
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["clone_status"] == "deploying"
        assert body["cloned_at"] is None
        assert body["failure_reason"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_status_extracts_failure_reason(client: TestClient) -> None:
    """failed 行 + description 含 [clone_failed] 标记 → 失败原因被解析。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(
        session_local,
        clone_status=VoiceCloneStatus.failed,
        description="\n[clone_failed] DashScope returned UNDEPLOYED",
    )
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/voice-packs/custom/clone_status_test/status"
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["clone_status"] == "failed"
        assert "UNDEPLOYED" in (body["failure_reason"] or "")
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_status_404_when_missing(client: TestClient) -> None:
    """voice_pack 不存在 → 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/voice-packs/custom/nope/status"
        )
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# GET list 分页 + 过滤
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_paginated_data(client: TestClient) -> None:
    """列表默认隐藏 deleted；分页字段齐全。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_a",
        clone_status=VoiceCloneStatus.ready,
    )
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_b",
        clone_status=VoiceCloneStatus.deploying,
    )
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_deleted",
        clone_status=VoiceCloneStatus.deleted,
    )
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/commerce/voice-packs/custom")
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["pagination"]["total"] == 2
        ids = {item["id"] for item in body["items"]}
        assert ids == {"clone_a", "clone_b"}

        # 显式 clone_status=deleted 时返回 deleted 行
        res = client.get(
            "/api/v1/commerce/voice-packs/custom?clone_status=deleted"
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["pagination"]["total"] == 1
        assert body["items"][0]["id"] == "clone_deleted"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_marks_deleted_and_calls_dashscope(
    client: TestClient,
) -> None:
    """DELETE 自定义音色 → 200 + clone_status=deleted + DashScope delete_voice 被调。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_to_delete",
        clone_status=VoiceCloneStatus.ready,
    )
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete(
            "/api/v1/commerce/voice-packs/custom/clone_to_delete"
        )
        assert res.status_code == 200, res.text

        async with session_local() as session:
            voice_pack = await session.get(VoicePack, "clone_to_delete")
            assert voice_pack is not None
            assert voice_pack.clone_status == VoiceCloneStatus.deleted

        assert "cosyvoice-v3.5-plus-myvoice-x" in (
            _FakeVoiceEnrollmentService.delete_calls
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_system_voice_returns_403(client: TestClient) -> None:
    """is_system=True 行禁止删除 → 403。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_system_test",
        is_system=True,
    )
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete(
            "/api/v1/commerce/voice-packs/custom/clone_system_test"
        )
        assert res.status_code == 403, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_404_when_missing(client: TestClient) -> None:
    """voice_pack 不存在 → 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete("/api/v1/commerce/voice-packs/custom/nope")
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_idempotent_when_dashscope_raises(
    client: TestClient,
) -> None:
    """DashScope delete_voice 抛错时仍把 DB 行标 deleted（幂等容忍）。"""
    session_local, engine = await _build_engine()
    await _seed_voice_pack(
        session_local,
        voice_pack_id="clone_idempotent",
        clone_status=VoiceCloneStatus.failed,
    )
    _FakeVoiceEnrollmentService._delete_should_raise = True
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete(
            "/api/v1/commerce/voice-packs/custom/clone_idempotent"
        )
        assert res.status_code == 200, res.text
        async with session_local() as session:
            voice_pack = await session.get(VoicePack, "clone_idempotent")
            assert voice_pack is not None
            assert voice_pack.clone_status == VoiceCloneStatus.deleted
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
