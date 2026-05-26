"""``ChapterAvPlanner`` Decision F 决策树测试（P3 W17 T17-7）。

为何存在
--------

Decision F 决策树是 P3 W17 的核心：在 TTS 真合成之前，对每一条
``ShotDialogLine`` 的文本做四步收敛：

1. ``estimate``：按 (text, line_mode, voice_pack.default_speed) 估算时长；
2. ``compare``：mismatch ratio = |estimated - target| / target，> 15% 触发动作；
3. ``speed_adjust``：在 [0.95, 1.15] 区间二分一个能让 ratio 落入 ±15% 的 speed；
4. ``llm_rewrite``：最多 3 次回灌 ``DurationRewriterAgent`` 改写文本；
5. ``hold``：仍未收敛 → 标记为需人工介入（避免无限循环，对应风险 R-P3-3 缓解）。

本文件用 fake rewriter agent 把 LLM 完全屏蔽掉，专注断言决策树的
分支选择与状态字段，确保每条分支都被覆盖到。
"""

# pylint: disable=redefined-outer-name,too-many-arguments

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

import pytest

from app.models.studio_shots import ShotDialogLine
from app.models.types import DialogueLineMode, VoiceGender, VoiceProvider
from app.models.voice_pack import VoicePack
from app.services.studio.chapter_av_planner import (
    MAX_REWRITE_ATTEMPTS,
    MISMATCH_THRESHOLD,
    ChapterAvPlanner,
    DurationEstimator,
)


# ---------------------------------------------------------------------------
# 共用 fixture：fake rewriter + ShotDialogLine 工厂
# ---------------------------------------------------------------------------


@dataclass
class _FakeRewriter:
    """记录调用次数与请求参数的桩 rewriter，按预设序列返回改写文本。

    这里没有走 ``DurationRewriterAgent`` 的真实 LLM 路径——单测要把
    决策树的“分支收敛”与“LLM 改写细节”解耦，前者由本文件保证，
    后者由 ``test_duration_rewriter_agent.py`` 单独覆盖。
    """

    rewrites: list[str] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)

    async def rewrite(
        self,
        *,
        original_text: str,
        target_chars: int,
        line_mode: DialogueLineMode,
    ) -> str:
        """按调用顺序返回 ``rewrites[i]``；超出长度时复用最后一项。"""

        idx = min(len(self.calls), len(self.rewrites) - 1) if self.rewrites else 0
        self.calls.append(
            {
                "original_text": original_text,
                "target_chars": target_chars,
                "line_mode": line_mode,
            }
        )
        if not self.rewrites:
            return original_text
        return self.rewrites[idx]


def _make_voice_pack(*, default_speed: float = 1.0) -> VoicePack:
    """构造一条最小可用的 ``VoicePack`` ORM 对象（不入库）。"""

    return VoicePack(
        id="cosyvoice_v2_test",
        name="测试音色",
        provider=VoiceProvider.aliyun_cosyvoice,
        provider_voice_id="longxiaochun_v2",
        language_code="zh-CN",
        gender=VoiceGender.female,
        description="unit-test",
        default_speed=default_speed,
        is_system=True,
        sort_order=0,
    )


def _make_dialog_line(
    *,
    text: str,
    line_mode: DialogueLineMode = DialogueLineMode.dialogue,
    line_id: int = 1,
) -> ShotDialogLine:
    """构造未入库的 ``ShotDialogLine``，仅供决策树测试读取字段。"""

    return ShotDialogLine(
        id=line_id,
        shot_detail_id="shot-detail-1",
        index=0,
        text=text,
        line_mode=line_mode,
    )


def _make_planner(rewriter: _FakeRewriter) -> ChapterAvPlanner:
    """工厂方法：把 ``_FakeRewriter`` 包装为 ``ChapterAvPlanner`` 期望的回调。"""

    async def _invoke(
        _db: object,
        *,
        original_text: str,
        target_chars: int,
        line_mode: DialogueLineMode,
    ) -> str:
        return await rewriter.rewrite(
            original_text=original_text,
            target_chars=target_chars,
            line_mode=line_mode,
        )

    return ChapterAvPlanner(rewriter_invoker=_invoke)


# ---------------------------------------------------------------------------
# 1. accept 分支
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_accept_when_estimate_within_threshold() -> None:
    """文本估时长落在 ±15% 内：直接 ``accept``，不调 rewriter。"""

    pack = _make_voice_pack()
    # 8 字 dialog @ 4 chars/sec ≈ 2000ms；目标 2000ms 完全匹配。
    line = _make_dialog_line(text="一二三四五六七八")
    rewriter = _FakeRewriter()
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=2000, voice_pack=pack
    )

    assert decision.action == "accept"
    assert decision.original_text == decision.final_text == line.text
    assert decision.suggested_speed == pytest.approx(1.0)
    assert decision.rewrite_attempts == 0
    assert decision.warning is None
    assert rewriter.calls == []


# ---------------------------------------------------------------------------
# 2. speed_adjust 分支
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_speed_adjust_when_clamped_speed_fits_threshold() -> None:
    """估时长稍超 ±15%，但 speed ∈ [0.95, 1.15] 微调即可收敛。"""

    pack = _make_voice_pack()
    # 18 字 @ 4 chars/sec = 4500ms。目标 4000ms：
    # ratio = (4500 - 4000) / 4000 = 0.125 < 0.15 → 直接 accept。
    # 因此换一个稍超阈值的：14 字 @ 4 = 3500ms，目标 3000ms：
    # ratio = 500/3000 ≈ 0.167 > 0.15 → 需要微调；
    # ideal_speed = (14 / 3) / 4 ≈ 1.167 → clamp 到 1.15 → effective_rate=4.6
    # → est = 14/4.6*1000 ≈ 3043ms → ratio ≈ 0.014 < 0.15 → speed_adjust。
    line = _make_dialog_line(text="一二三四五六七八九十百千万亿")  # 14 字
    rewriter = _FakeRewriter()
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=3000, voice_pack=pack
    )

    assert decision.action == "speed_adjust"
    assert decision.original_text == decision.final_text == line.text
    assert 0.95 <= decision.suggested_speed <= 1.15
    assert decision.rewrite_attempts == 0
    assert decision.warning is None
    assert rewriter.calls == []


# ---------------------------------------------------------------------------
# 3. llm_rewrite 一次成功
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_llm_rewrite_first_attempt_success() -> None:
    """首次 LLM 改写产出落入 ±15% 的文本：``llm_rewrite``、attempts=1。"""

    pack = _make_voice_pack()
    # 30 字 @ 4 chars/sec = 7500ms。目标 2000ms：
    # ratio = 5500/2000 = 2.75 → speed=0.95 仍远超阈值 → 进入 LLM 改写。
    long_text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥风雨雷电山川河海"
    line = _make_dialog_line(text=long_text)

    # 改写后 8 字 @ 4 chars/sec = 2000ms → 完全命中。
    rewriter = _FakeRewriter(rewrites=["甲乙丙丁戊己庚辛"])
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=2000, voice_pack=pack
    )

    assert decision.action == "llm_rewrite"
    assert decision.original_text == long_text
    assert decision.final_text == "甲乙丙丁戊己庚辛"
    assert decision.rewrite_attempts == 1
    assert decision.warning is None
    assert len(rewriter.calls) == 1
    # rewriter 收到的 target_chars 需基于 line_mode + duration 推算。
    call = rewriter.calls[0]
    assert call["original_text"] == long_text
    assert call["line_mode"] == DialogueLineMode.dialogue
    # dialog 模式：4 chars/sec * 2s = 8。
    assert call["target_chars"] == 8


# ---------------------------------------------------------------------------
# 4. hold 分支：3 次改写均失败
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_hold_when_three_rewrite_attempts_all_fail() -> None:
    """连续 3 次 LLM 改写仍超阈值：``hold``，warning 含 ``MAX_REWRITE_ATTEMPTS``。"""

    pack = _make_voice_pack()
    long_text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥风雨雷电山川河海"
    line = _make_dialog_line(text=long_text)

    # 每次都返回仍然过长的文本，确保 ratio 永远 > 0.15。
    too_long = "这段文本依然非常长足以让所有估算都超出阈值无法收敛到目标时长的允许窗口内"
    rewriter = _FakeRewriter(
        rewrites=[too_long, too_long + "再加点", too_long + "再加更多"]
    )
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=2000, voice_pack=pack
    )

    assert decision.action == "hold"
    assert decision.rewrite_attempts == MAX_REWRITE_ATTEMPTS
    assert decision.warning is not None
    assert str(MAX_REWRITE_ATTEMPTS) in decision.warning
    assert "人工" in decision.warning
    # rewriter 应被调用恰好 MAX_REWRITE_ATTEMPTS 次。
    assert len(rewriter.calls) == MAX_REWRITE_ATTEMPTS


# ---------------------------------------------------------------------------
# 5. hold warning 文案
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_hold_warning_message_contract() -> None:
    """``hold`` 分支必须给出可执行的运营提示文案，避免静默卡死。"""

    pack = _make_voice_pack()
    long_text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"
    line = _make_dialog_line(text=long_text)
    too_long = "依然过长无法收敛的兜底文案就让它命中 hold 分支吧再多写点确保超阈值的足够长"
    rewriter = _FakeRewriter(rewrites=[too_long, too_long, too_long])
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=2000, voice_pack=pack
    )

    assert decision.action == "hold"
    assert decision.warning is not None
    # 文案必须包含尝试次数与人工介入提示，便于前端运营面板直接展示。
    assert "改写" in decision.warning
    assert "人工" in decision.warning


# ---------------------------------------------------------------------------
# 6. mixed-language handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_handles_mixed_language_without_crashing() -> None:
    """混排文本同样能跑完整决策树，不应抛异常或进入死循环。"""

    pack = _make_voice_pack()
    line = _make_dialog_line(text="今天 the demo 很赞 it works perfectly fine")
    rewriter = _FakeRewriter()
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=5000, voice_pack=pack
    )
    # 混排估算后必然会得到合法 action，不允许是 None / 未定义值。
    assert decision.action in {"accept", "speed_adjust", "llm_rewrite", "hold"}
    assert decision.estimated_ms >= 0


# ---------------------------------------------------------------------------
# 7. 边界：空文本
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_empty_text_routes_to_accept_or_rewrite_without_crashing() -> None:
    """空文本边界：估时长=0，目标>0 → ratio=1 → 触发后续分支但不抛错。"""

    pack = _make_voice_pack()
    line = _make_dialog_line(text="")
    rewriter = _FakeRewriter(rewrites=[""])
    planner = _make_planner(rewriter)

    decision = await planner.plan_dialog_line(
        db=None, line=line, shot_duration_ms=2000, voice_pack=pack
    )
    assert decision.action in {"accept", "speed_adjust", "llm_rewrite", "hold"}
    assert decision.estimated_ms >= 0


# ---------------------------------------------------------------------------
# 8. MISMATCH_THRESHOLD 常量契约
# ---------------------------------------------------------------------------


def test_planner_threshold_constant_locked_at_15_percent() -> None:
    """常量必须严格等于 0.15，否则等同于偷偷放宽 Decision F 决策标准。"""

    assert MISMATCH_THRESHOLD == 0.15


def test_planner_max_rewrite_attempts_locked_at_three() -> None:
    """风险 R-P3-3 缓解：连续 3 次回灌触发 hold；该常量是契约边界。"""

    assert MAX_REWRITE_ATTEMPTS == 3


# ---------------------------------------------------------------------------
# 9. type hints / API 形态
# ---------------------------------------------------------------------------


def test_planner_accepts_async_rewriter_invoker() -> None:
    """构造器必须接受一个 ``async`` 回调，而非具体 Agent 类，便于单测注入。"""

    async def _identity(
        _db: object,
        *,
        original_text: str,
        target_chars: int,  # pylint: disable=unused-argument
        line_mode: DialogueLineMode,  # pylint: disable=unused-argument
    ) -> str:
        return original_text

    invoker: Callable[..., Awaitable[str]] = _identity
    planner = ChapterAvPlanner(rewriter_invoker=invoker)
    assert planner is not None


def test_estimator_re_export_for_consumers() -> None:
    """``DurationEstimator`` 必须能从 chapter_av_planner 直接导入，便于消费方复用。"""

    pack = _make_voice_pack()
    est = DurationEstimator.estimate(
        text="测试", line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    assert est.estimated_ms > 0
