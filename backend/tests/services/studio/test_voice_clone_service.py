"""W29-T4 voice_clone_service 单元测试。

测试覆盖：
    1. validate_audio_metadata：合规路径 + 各拒绝路径（format / size /
       duration / sample_rate / channels / 不可解析）。
    2. create_voice_remote / query_clone_status / delete_voice_remote：
       通过 monkeypatch DashScope SDK 类，验证 region 切换 + 状态映射。
    3. persist_voice_pack：W19b 契约——commit 后 row 立即可见，
       clone_status=deploying / sample_audio_oss_key 落地。

按 W29 instructions：DashScope 调用不打真实 API，全部用 monkeypatch
SDK 类替代。region 切换通过断言 ``dashscope.base_http_api_url`` 验证。
"""

# pylint: disable=protected-access,redefined-outer-name,too-few-public-methods

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pytest
import pytest_asyncio
import soundfile as sf
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 必须 import 全部模型以确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

import dashscope
from app.core.contracts.voice_pack_contracts import CustomVoiceCreateRequest
from app.core.db import Base
from app.models.types import VoiceCloneStatus, VoiceRegion
from app.models.voice_pack import VoicePack
from app.services.studio import voice_clone_service
from app.services.studio.voice_clone_service import (
    AudioValidationFailure,
    create_voice_remote,
    delete_voice_remote,
    persist_voice_pack,
    query_clone_status,
    validate_audio_metadata,
)


# ---------------------------------------------------------------------------
# wav 字节流构造：用 numpy 生成符合各拒绝路径的样本
# ---------------------------------------------------------------------------


def _make_wav_bytes(
    *,
    duration_sec: float = 15.0,
    sample_rate_hz: int = 16000,
    channels: int = 1,
) -> bytes:
    """生成一段静音 WAV 字节流，便于按维度构造测试样本。"""
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
# validate_audio_metadata 拒绝路径
# ---------------------------------------------------------------------------


def test_validate_audio_metadata_happy_path() -> None:
    """合规音频应当被接受。"""
    wav = _make_wav_bytes(duration_sec=15.0, sample_rate_hz=16000, channels=1)
    validation, failures = validate_audio_metadata(wav, declared_format="wav")
    assert failures == []
    assert validation is not None
    assert validation.format == "wav"
    assert validation.sample_rate_hz == 16000
    assert validation.channels == 1
    assert 14.5 < validation.duration_sec < 15.5


def test_validate_audio_metadata_rejects_bad_format_label() -> None:
    """declared_format 不在 wav/mp3/m4a 集合应触发 format 失败。"""
    wav = _make_wav_bytes()
    validation, failures = validate_audio_metadata(wav, declared_format="ogg")
    assert validation is None
    assert any(f.field == "format" for f in failures)


def test_validate_audio_metadata_rejects_too_short() -> None:
    """duration < 10s 应被拒绝。"""
    wav = _make_wav_bytes(duration_sec=5.0)
    validation, failures = validate_audio_metadata(wav, declared_format="wav")
    assert validation is None
    assert any(f.field == "duration_sec" for f in failures)


def test_validate_audio_metadata_rejects_too_long() -> None:
    """duration > 60s 应被拒绝。"""
    wav = _make_wav_bytes(duration_sec=70.0)
    validation, failures = validate_audio_metadata(wav, declared_format="wav")
    assert validation is None
    assert any(f.field == "duration_sec" for f in failures)


def test_validate_audio_metadata_rejects_low_sample_rate() -> None:
    """sample_rate < 16kHz 应被拒绝。"""
    wav = _make_wav_bytes(duration_sec=15.0, sample_rate_hz=8000)
    validation, failures = validate_audio_metadata(wav, declared_format="wav")
    assert validation is None
    assert any(f.field == "sample_rate_hz" for f in failures)


def test_validate_audio_metadata_rejects_oversize() -> None:
    """size > 10MB 应被拒绝（用 fake bytes 模拟）。"""
    big = b"\x00" * (11 * 1024 * 1024)
    validation, failures = validate_audio_metadata(big, declared_format="wav")
    assert validation is None
    assert any(f.field == "size" for f in failures)


def test_validate_audio_metadata_rejects_unparseable() -> None:
    """完全不是音频的字节流应触发 format 失败。"""
    junk = b"this is not audio at all"
    validation, failures = validate_audio_metadata(junk, declared_format="wav")
    assert validation is None
    assert any(f.field == "format" for f in failures)


def test_audio_validation_failure_to_dict() -> None:
    """AudioValidationFailure.to_dict 输出 JSON 可序列化的 dict。"""
    failure = AudioValidationFailure(field="size", expected="<=10MB", actual="11MB")
    assert failure.to_dict() == {
        "field": "size",
        "expected": "<=10MB",
        "actual": "11MB",
    }


# ---------------------------------------------------------------------------
# DashScope SDK monkeypatch：模拟 create / query / delete
# ---------------------------------------------------------------------------


class _FakeVoiceEnrollmentService:
    """替身 SDK：在 monkeypatch 中替换 :class:`VoiceEnrollmentService`。

    通过类属性 :data:`_create_returns` / :data:`_query_returns` / :data:`_delete_should_raise`
    控制返回值，方便不同测试覆盖 OK / DEPLOYING / UNDEPLOYED 三种轨迹。
    """

    create_calls: list[dict[str, Any]] = []
    query_calls: list[str] = []
    delete_calls: list[str] = []
    _create_returns: str = "cosyvoice-v3.5-plus-myvoice-fakehash"
    _query_returns: dict[str, Any] = {"status": "DEPLOYING"}
    _delete_should_raise: bool = False

    def create_voice(self, **kwargs: Any) -> str:  # noqa: D401
        """记录调用并返回固定 voice_id。"""
        self.create_calls.append(kwargs)
        return self._create_returns

    def query_voice(self, voice_id: str) -> dict[str, Any]:  # noqa: D401
        """记录调用并返回预设的 status dict。"""
        self.query_calls.append(voice_id)
        return self._query_returns

    def delete_voice(self, voice_id: str) -> None:  # noqa: D401
        """记录调用；按 :data:`_delete_should_raise` 决定是否抛异常。"""
        self.delete_calls.append(voice_id)
        if self._delete_should_raise:
            raise RuntimeError("voice not found")


@pytest.fixture(autouse=True)
def _reset_dashscope_state(monkeypatch: pytest.MonkeyPatch):
    """每个 test 前后重置 DashScope 全局 base_url 与 fake SDK 计数。"""
    monkeypatch.setattr(dashscope, "base_http_api_url", "")
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
    yield


@pytest.mark.asyncio
async def test_create_voice_remote_switches_to_beijing() -> None:
    """region=cn-beijing 应把 base_http_api_url 切到北京 endpoint。"""
    voice_id = await create_voice_remote(
        target_model="cosyvoice-v3.5-plus",
        prefix="myvoice",
        sample_url="https://oss/sample.wav",
        region=VoiceRegion.cn_beijing,
        language_hints=["zh"],
    )
    assert voice_id == "cosyvoice-v3.5-plus-myvoice-fakehash"
    assert dashscope.base_http_api_url.endswith("dashscope.aliyuncs.com/api/v1")
    assert _FakeVoiceEnrollmentService.create_calls[0]["target_model"] == (
        "cosyvoice-v3.5-plus"
    )


@pytest.mark.asyncio
async def test_create_voice_remote_switches_to_singapore() -> None:
    """region=ap-singapore 应把 base_http_api_url 切到新加坡 endpoint。"""
    await create_voice_remote(
        target_model="cosyvoice-v3-plus",
        prefix="enmale",
        sample_url="https://oss/en.wav",
        region=VoiceRegion.ap_singapore,
        language_hints=["en"],
    )
    assert dashscope.base_http_api_url.endswith(
        "dashscope-intl.aliyuncs.com/api/v1"
    )


@pytest.mark.asyncio
async def test_query_clone_status_maps_deploying() -> None:
    """DashScope status=DEPLOYING -> VoiceCloneStatus.deploying。"""
    _FakeVoiceEnrollmentService._query_returns = {"status": "DEPLOYING"}
    status, reason = await query_clone_status(
        voice_id="vid-x", region=VoiceRegion.cn_beijing
    )
    assert status == VoiceCloneStatus.deploying
    assert reason is None


@pytest.mark.asyncio
async def test_query_clone_status_maps_ok() -> None:
    """DashScope status=OK -> VoiceCloneStatus.ready。"""
    _FakeVoiceEnrollmentService._query_returns = {"status": "OK"}
    status, reason = await query_clone_status(
        voice_id="vid-x", region=VoiceRegion.cn_beijing
    )
    assert status == VoiceCloneStatus.ready
    assert reason is None


@pytest.mark.asyncio
async def test_query_clone_status_maps_undeployed() -> None:
    """DashScope status=UNDEPLOYED -> VoiceCloneStatus.failed。"""
    _FakeVoiceEnrollmentService._query_returns = {"status": "UNDEPLOYED"}
    status, reason = await query_clone_status(
        voice_id="vid-x", region=VoiceRegion.cn_beijing
    )
    assert status == VoiceCloneStatus.failed
    assert reason == "DashScope returned UNDEPLOYED"


@pytest.mark.asyncio
async def test_delete_voice_remote_idempotent_on_error() -> None:
    """SDK 抛异常时 :func:`delete_voice_remote` 应返回 ``False`` 容忍幂等。"""
    _FakeVoiceEnrollmentService._delete_should_raise = True
    deleted = await delete_voice_remote(
        voice_id="vid-x", region=VoiceRegion.cn_beijing
    )
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_voice_remote_returns_true_on_success() -> None:
    """SDK 正常返回时 :func:`delete_voice_remote` 应返回 ``True``。"""
    _FakeVoiceEnrollmentService._delete_should_raise = False
    deleted = await delete_voice_remote(
        voice_id="vid-x", region=VoiceRegion.cn_beijing
    )
    assert deleted is True
    assert "vid-x" in _FakeVoiceEnrollmentService.delete_calls


# ---------------------------------------------------------------------------
# persist_voice_pack：W19b 契约
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎；与其它 worker 测试同样的模板。"""
    db_path = tmp_path / "voice-clone-service.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_voice_pack_commits_immediately(session_factory) -> None:
    """persist_voice_pack 必须在 return 前 commit；row 在新 session 里立即可见。"""
    request = CustomVoiceCreateRequest(
        prefix="myvoice",
        target_model="cosyvoice-v3.5-plus",
        region=VoiceRegion.cn_beijing,
        display_name="测试音色",
        language_hints=["zh"],
    )
    async with session_factory() as session:
        voice_pack = await persist_voice_pack(
            session,
            request=request,
            sample_audio_oss_key="voice-clone-samples/abc.wav",
            dashscope_voice_id="cosyvoice-v3.5-plus-myvoice-xxxxx",
        )
        assert voice_pack.id.startswith("clone_")
        assert voice_pack.clone_status == VoiceCloneStatus.deploying
        assert voice_pack.is_system is False
        assert voice_pack.target_model == "cosyvoice-v3.5-plus"
        assert voice_pack.region == VoiceRegion.cn_beijing
        voice_pack_id = voice_pack.id

    # W19b 契约：另开一个 session，行必须已经落库可见。
    async with session_factory() as fresh_session:
        row = await fresh_session.get(VoicePack, voice_pack_id)
        assert row is not None
        assert row.clone_status == VoiceCloneStatus.deploying
        assert row.sample_audio_oss_key == "voice-clone-samples/abc.wav"
        assert row.provider_voice_id == "cosyvoice-v3.5-plus-myvoice-xxxxx"
