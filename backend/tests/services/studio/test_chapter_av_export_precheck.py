"""``chapter_av_export`` 一致性前置门测试（W27-T4，P4 Wave C 3/3）。

覆盖 4 个核心场景：

1. test_blocks_when_any_shot_consistency_fail：任一 shot ``fail`` → 422
2. test_passes_when_all_warning_or_pass_or_none：全 ``warning`` / ``pass`` /
   ``None`` 混合 → 不抛
3. test_bypass_env_skips_check：``chapter_av_export_bypass_consistency=True``
   即使有 ``fail`` shot 也放行
4. test_failing_shot_ids_in_detail：422 detail 必须含 ``failing_shot_ids``
   list + ``code=consistency_gates_failed``，前端可批量 regen
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.models.studio_shots import Shot
from app.services.studio.chapter_av_export_task import (
    CONSISTENCY_GATE_ERROR_CODE,
    _assert_consistency_gates_pass,
)


def _make_shot(shot_id: str, status: str | None) -> Shot:
    """构造仅设 id + consistency_status 的 Shot（其余字段不影响前置门判定）。"""
    shot = Shot(
        id=shot_id,
        chapter_id="ch_test",
        index=0,
        title=f"shot {shot_id}",
    )
    shot.consistency_status = status
    return shot


def test_blocks_when_any_shot_consistency_fail() -> None:
    """1 个 shot ``fail`` + 其余 ``pass`` → 422 阻止导出。"""
    shots = [
        _make_shot("sh1", "pass"),
        _make_shot("sh2", "fail"),
        _make_shot("sh3", "pass"),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _assert_consistency_gates_pass("ch1", shots)
    assert exc_info.value.status_code == 422


def test_passes_when_all_warning_or_pass_or_none() -> None:
    """``pass`` / ``warning`` / ``None`` 三态混合 → 全部放行不抛。"""
    shots = [
        _make_shot("sh1", "pass"),
        _make_shot("sh2", "warning"),
        _make_shot("sh3", None),
    ]
    _assert_consistency_gates_pass("ch1", shots)


def test_passes_for_empty_shots_list() -> None:
    """空 shots（空章节或全部跳过）→ 不抛。"""
    _assert_consistency_gates_pass("ch1", [])


def test_bypass_env_skips_check() -> None:
    """``chapter_av_export_bypass_consistency=True`` → 即使 fail 也放行。"""
    bypass_settings = Settings(chapter_av_export_bypass_consistency=True)
    shots = [_make_shot("sh1", "fail"), _make_shot("sh2", "fail")]
    _assert_consistency_gates_pass("ch1", shots, settings=bypass_settings)


def test_failing_shot_ids_in_detail() -> None:
    """422 detail 必须含 code + failing_shot_ids + chapter_id 用于前端 regen。"""
    shots = [
        _make_shot("sh_a", "pass"),
        _make_shot("sh_b", "fail"),
        _make_shot("sh_c", "fail"),
        _make_shot("sh_d", "warning"),
    ]
    with pytest.raises(HTTPException) as exc_info:
        _assert_consistency_gates_pass("ch_xyz", shots)
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == CONSISTENCY_GATE_ERROR_CODE
    assert detail["chapter_id"] == "ch_xyz"
    assert set(detail["failing_shot_ids"]) == {"sh_b", "sh_c"}
