"""W29-T1 自定义音色训练字段 + DTO 单元测试。

覆盖目标：
    1. alembic 0018 升降级：在 0017 baseline 上 ``upgrade head`` 后
       ``voice_packs`` 上多出 5 个新列；``downgrade -1`` 后干净移除。
    2. backfill 行为：``upgrade head`` 后历史 ``is_system=TRUE`` 行的
       ``clone_status`` 被回填为 ``"ready"``。
    3. 新枚举 :class:`VoiceCloneStatus` / :class:`VoiceRegion` 值集合稳定。
    4. :class:`CustomVoiceCreateRequest` 校验各拒绝路径
       （prefix 太长 / 含特殊字符 / target_model 非法 / display_name 为空）。
    5. :class:`AudioMetadataValidation` 校验各拒绝路径
       （format / duration 越界 / size 超限 / sample_rate / channels 越界）。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine
from pydantic import ValidationError

from app.config import settings
from app.core.contracts.voice_pack_contracts import (
    AudioMetadataValidation,
    CustomVoiceCreateRequest,
)
from app.core.db import Base
from app.models.types import VoiceCloneStatus, VoiceRegion

# 模型必须 import，确保 Base.metadata 拥有完整定义。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.compliance  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.llm  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.studio  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.task  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.task_links  # noqa: F401  pylint: disable=unused-import,wrong-import-position
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import,wrong-import-position


# 0018 在 voice_packs 表上新增的 5 个列
NEW_COLUMNS_0018: tuple[str, ...] = (
    "target_model",
    "region",
    "clone_status",
    "sample_audio_oss_key",
    "cloned_at",
)


def _alembic_dir() -> Path:
    """返回 ``backend/alembic`` 的绝对路径。"""
    return Path(__file__).resolve().parent.parent.parent.parent / "alembic"


def _make_alembic_config(db_url: str) -> Config:
    """构造一个指向给定 SQLite URL 的 ``alembic.Config``。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _setup_pre_0018_schema(engine: Engine) -> None:
    """搭建 "pre-0018" 状态：建出当前完整 ORM schema，再丢掉 0018 引入的 5 列。

    SQLite 不支持原生 DROP COLUMN with FK；这里把表复制到独立 MetaData 上
    并在复制时跳过 0018 列，避免污染共享 ``Base.metadata``。
    """
    fresh = MetaData()
    skip_cols = set(NEW_COLUMNS_0018)

    for source in Base.metadata.sorted_tables:
        copy_target = source.to_metadata(
            fresh,
            referred_schema_fn=lambda _t, _to_schema, _ck, referred_schema: referred_schema,
        )
        if source.name == "voice_packs":
            for col_name in skip_cols:
                if col_name in copy_target.columns:
                    col = copy_target.columns[col_name]
                    copy_target._columns.remove(col)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    fresh.create_all(bind=engine)


def _stamp_version(engine: Engine, version: str) -> None:
    """将 ``alembic_version`` 表标记为指定版本号。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": version},
        )


@pytest.fixture()
def tmp_engine() -> Iterator[Engine]:
    """提供一个临时文件 SQLite engine。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "alembic_0018_test.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url, future=True)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture()
def baseline_engine(
    tmp_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Engine:
    """返回一个 alembic_version=0017、缺少 0018 schema 的临时 engine。"""
    _setup_pre_0018_schema(tmp_engine)
    _stamp_version(tmp_engine, "0017")
    monkeypatch.setattr(settings, "database_url", str(tmp_engine.url))
    return tmp_engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    """返回指定表的列名集合。"""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


# ---------------------------------------------------------------------------
# alembic 0018 升降级
# ---------------------------------------------------------------------------


def test_upgrade_head_adds_five_columns(baseline_engine: Engine) -> None:
    """upgrade head 后必须在 voice_packs 上多出 5 个列。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    cols = _table_columns(baseline_engine, "voice_packs")
    for required in NEW_COLUMNS_0018:
        assert required in cols, f"voice_packs missing new column: {required}"


def test_downgrade_removes_five_columns(baseline_engine: Engine) -> None:
    """downgrade -1 (head 0018 -> 0017) 后必须干净移除 5 个新列。"""
    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")

    cols = _table_columns(baseline_engine, "voice_packs")
    for col in NEW_COLUMNS_0018:
        assert col not in cols, f"{col} should be removed by downgrade"


def test_upgrade_backfills_system_rows(baseline_engine: Engine) -> None:
    """upgrade head 后，历史 is_system=TRUE 行的 clone_status 必须被回填为 'ready'。"""
    # 在 baseline（0017，无新列）上塞一条 system 行
    with baseline_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO voice_packs "
                "(id, name, provider, provider_voice_id, language_code, "
                " gender, description, default_speed, is_system, sort_order, "
                " created_at, updated_at) "
                "VALUES "
                "('test_seed_voice', 'TestSeed', 'aliyun_cosyvoice', 'longxiaochun_v2', "
                " 'zh-CN', 'neutral', '', 1.0, 1, 0, "
                " '2026-05-28 00:00:00', '2026-05-28 00:00:00')"
            )
        )

    cfg = _make_alembic_config(str(baseline_engine.url))
    command.upgrade(cfg, "head")

    with baseline_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT clone_status FROM voice_packs WHERE id='test_seed_voice'"
            )
        ).scalar_one()
    assert result == "ready", (
        f"expected backfill clone_status='ready' for is_system=TRUE rows, got {result!r}"
    )


# ---------------------------------------------------------------------------
# 枚举值集合
# ---------------------------------------------------------------------------


def test_voice_clone_status_values_stable() -> None:
    """VoiceCloneStatus 必须包含 4 个状态。"""
    assert {member.value for member in VoiceCloneStatus} == {
        "deploying",
        "ready",
        "failed",
        "deleted",
    }


def test_voice_region_values_stable() -> None:
    """VoiceRegion 必须包含 cn-beijing 与 ap-singapore 两套端点。"""
    assert {member.value for member in VoiceRegion} == {
        "cn-beijing",
        "ap-singapore",
    }


# ---------------------------------------------------------------------------
# CustomVoiceCreateRequest 拒绝路径
# ---------------------------------------------------------------------------


def _valid_create_request_kwargs() -> dict:
    """构造一组合规的 :class:`CustomVoiceCreateRequest` 入参，用于按需修改单字段。"""
    return {
        "prefix": "myvoice",
        "target_model": "cosyvoice-v3.5-plus",
        "region": VoiceRegion.cn_beijing,
        "display_name": "测试音色",
        "language_hints": ["zh"],
        "description": None,
        "archetype_hint": None,
    }


def test_create_request_happy_path() -> None:
    """合规入参必须能被构造成功。"""
    req = CustomVoiceCreateRequest(**_valid_create_request_kwargs())
    assert req.prefix == "myvoice"
    assert req.target_model == "cosyvoice-v3.5-plus"
    assert req.region == VoiceRegion.cn_beijing


def test_create_request_rejects_long_prefix() -> None:
    """prefix 超过 10 字符必须被 422 拒绝。"""
    kwargs = _valid_create_request_kwargs()
    kwargs["prefix"] = "a" * 11
    with pytest.raises(ValidationError):
        CustomVoiceCreateRequest(**kwargs)


def test_create_request_rejects_special_char_prefix() -> None:
    """prefix 含 - / . / 中文等必须被拒绝。"""
    kwargs = _valid_create_request_kwargs()
    kwargs["prefix"] = "my-voice"
    with pytest.raises(ValidationError):
        CustomVoiceCreateRequest(**kwargs)

    kwargs["prefix"] = "我的音色"
    with pytest.raises(ValidationError):
        CustomVoiceCreateRequest(**kwargs)


def test_create_request_rejects_invalid_target_model() -> None:
    """target_model 不在 Literal 集合内必须被拒绝。"""
    kwargs = _valid_create_request_kwargs()
    kwargs["target_model"] = "cosyvoice-v2"
    with pytest.raises(ValidationError):
        CustomVoiceCreateRequest(**kwargs)


def test_create_request_rejects_empty_display_name() -> None:
    """display_name 为空字符串必须被拒绝。"""
    kwargs = _valid_create_request_kwargs()
    kwargs["display_name"] = ""
    with pytest.raises(ValidationError):
        CustomVoiceCreateRequest(**kwargs)


# ---------------------------------------------------------------------------
# AudioMetadataValidation 拒绝路径
# ---------------------------------------------------------------------------


def _valid_audio_metadata_kwargs() -> dict:
    """构造一组合规的 :class:`AudioMetadataValidation` 入参。"""
    return {
        "format": "wav",
        "duration_sec": 15.0,
        "size_bytes": 5 * 1024 * 1024,
        "sample_rate_hz": 44100,
        "channels": 1,
    }


def test_audio_metadata_happy_path() -> None:
    """合规音频元信息必须能构造成功。"""
    av = AudioMetadataValidation(**_valid_audio_metadata_kwargs())
    assert av.format == "wav"
    assert av.duration_sec == pytest.approx(15.0)


def test_audio_metadata_rejects_bad_format() -> None:
    """format 不在 wav/mp3/m4a 集合内必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["format"] = "ogg"
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)


def test_audio_metadata_rejects_too_short_duration() -> None:
    """duration_sec < 10 必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["duration_sec"] = 5.0
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)


def test_audio_metadata_rejects_too_long_duration() -> None:
    """duration_sec > 60 必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["duration_sec"] = 61.0
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)


def test_audio_metadata_rejects_oversize() -> None:
    """size_bytes > 10 MB 必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["size_bytes"] = 11 * 1024 * 1024
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)


def test_audio_metadata_rejects_low_sample_rate() -> None:
    """sample_rate_hz < 16000 必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["sample_rate_hz"] = 8000
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)


def test_audio_metadata_rejects_too_many_channels() -> None:
    """channels > 2 必须被拒绝。"""
    kwargs = _valid_audio_metadata_kwargs()
    kwargs["channels"] = 6
    with pytest.raises(ValidationError):
        AudioMetadataValidation(**kwargs)
