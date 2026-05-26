"""章节 AV 时间轴规划器 (P3 W17 T17-7 — Decision F).

为何存在
--------

TTS 合成前必须先 reconcile ``(text, voice_pack, shot.duration)`` 三元组：
文本太长或太短都会破坏镜头节奏。实测 CosyVoice ≈ 3-4 zh 字 / 秒
（视音色而异），mismatch > 15% 即触发改写。

Decision F 决策树（来自 P3 plan doc + R-P3-3 缓解）::

    1. ESTIMATE: 用 DurationEstimator 按 (text, language, base_speed)
       估时长（毫秒）。
    2. COMPARE: |estimated - shot.duration_ms| / shot.duration_ms > 0.15
       视为 mismatch。
    3. ACTION:
       a) Try SPEED_ADJUST: 在 [0.95, 1.15] 区间内挑一个能让 estimated
          落入 ±15% 的 speed；命中则 accept。
       b) 失败 → LLM_REWRITE: 调 DurationRewriterAgent，要求把文本改写
          为 ≤ target_chars（保留语义）；最多 ``MAX_REWRITE_ATTEMPTS`` 次。
       c) 仍失败 → HOLD: 标记 ``needs_user_intervention``，并把告警写入
          ``ChapterAvPlanResult.warnings``，避免无限循环（R-P3-3 缓解）。

输出契约
--------

- :class:`DurationEstimate`：单条文本的估算结果（不入库，纯计算结构）。
- :class:`DurationDecision`：单条 ``ShotDialogLine`` 的决策结果，
  worker 据此回写 ``start_time_ms`` / ``end_time_ms`` 与可能更新的
  ``text``；不写 ``tts_audio_file_id``（这一步留给 ``tts_generate_worker``
  在合成完成后回填）。
- :class:`ChapterAvPlanResult`：整章节级别的汇总结果，包含 decision 列表、
  hold 行 ID 与 warning 数。

设计要点
--------

- ``DurationEstimator`` 完全是同步计算模块，不依赖 LLM / DB；
- ``ChapterAvPlanner`` 通过依赖注入 ``rewriter_invoker`` 解耦真实
  Agent 调用，便于单测；worker 侧再注入真实的 LLM 桥接器。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from app.models.studio_shots import ShotDialogLine
from app.models.types import AudioStrategy, DialogueLineMode
from app.models.voice_pack import VoicePack

# ---------------------------------------------------------------------------
# 决策常量（契约边界）
# ---------------------------------------------------------------------------

#: ±15% 阈值。超出即视为 mismatch，触发后续微调 / 改写 / hold 分支。
MISMATCH_THRESHOLD: float = 0.15

#: speed 微调下限（plan doc Decision F：0.95-1.15 微调区间）。
SPEED_MIN: float = 0.95

#: speed 微调上限。
SPEED_MAX: float = 1.15

#: LLM 改写最大尝试次数。R-P3-3 缓解：连续 ``≥ 3`` 次仍未收敛即 hold，
#: 避免无限回灌死循环。
MAX_REWRITE_ATTEMPTS: int = 3

#: 中文 dialog 模式估算速率（chars/sec）；plan doc 上限 ``≤ 4 × duration_sec``。
ZH_CHARS_PER_SEC_DIALOG: float = 4.0

#: 中文旁白（voice_over）模式估算速率；旁白字幕一般匀速更慢。
ZH_CHARS_PER_SEC_NARRATION: float = 3.0

#: 英文按 word/sec 折算（约 0.5s/word），再乘 5 得到 chars/sec 等效速率。
EN_WORDS_PER_SEC: float = 2.0


#: 决策动作枚举：accept / speed_adjust / llm_rewrite / hold / skip_native。
#:
#: - ``accept`` / ``speed_adjust`` / ``llm_rewrite`` / ``hold``：Decision F 决策树
#:   常规四个落点，参见模块顶部 docstring。
#: - ``skip_native``（P3 W17 收尾，Decision D 修订）：``Shot.audio_strategy ==
#:   keep_native`` 时 planner 整树跳过；模型自带原音决定时长，planner 不做
#:   text/speed reconcile，下游靠 paraformer-v2 ASR 反推时间戳生成字幕。
DecisionAction = Literal["accept", "speed_adjust", "llm_rewrite", "hold", "skip_native"]


#: ``rewriter_invoker`` 协议：(db, *, original_text, target_chars, line_mode) -> rewritten_text。
#: 抽象成回调而不是直接依赖具体 Agent，便于单测注入 fake，并让 worker
#: 侧自由选择 sync LLM 桥接策略。
RewriterInvoker = Callable[..., Awaitable[str]]


# ---------------------------------------------------------------------------
# DTO（dataclass，避免引入 Pydantic 依赖；这一层不跨进程）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DurationEstimate:
    """字符数→TTS 估算时长（毫秒）。

    字段:
        text: 原始文本。
        language: 检测到的语言族（zh / en / mixed）。
        voice_pack_id: 估算所用音色包 ID，便于 trace。
        base_speed: ``speed * voice_pack.default_speed`` 实际倍率。
        estimated_ms: 估算时长（毫秒）。
        char_count: 计入估算的字符数（已剔除空白等无音字符）。
        chars_per_sec: 估算所用 effective chars-per-sec 速率。
    """

    text: str
    language: Literal["zh", "en", "mixed"]
    voice_pack_id: str
    base_speed: float
    estimated_ms: int
    char_count: int
    chars_per_sec: float


@dataclass
class DurationDecision:
    """单条 ``ShotDialogLine`` 的 duration 决策结果。

    ``action`` 是决策树最终分支；``original_text`` / ``final_text`` 用于
    判断是否需要回写 ``ShotDialogLine.text``；``suggested_speed`` 是
    speed_adjust 路径产出的微调 speed，其它路径保持 1.0。

    字段:
        dialog_line_id: ``ShotDialogLine.id``。
        action: 决策动作。
        original_text: 决策前的原始文本。
        final_text: 决策后落库的文本（accept/speed_adjust 路径与原文一致）。
        suggested_speed: 落库 / 合成时建议使用的 speed。
        target_duration_ms: 目标镜头时长（毫秒）。
        estimated_ms: 决策最终采用的估算时长。
        rewrite_attempts: LLM 改写尝试次数（accept/speed_adjust 为 0）。
        warning: 仅 hold 分支非空，给出可在前端展示的运营提示。
    """

    dialog_line_id: int
    action: DecisionAction
    original_text: str
    final_text: str
    suggested_speed: float
    target_duration_ms: int
    estimated_ms: int
    rewrite_attempts: int = 0
    warning: str | None = None


@dataclass
class ChapterAvPlanResult:
    """整章 AV plan 输出。

    ``warnings`` 中每个元素由 worker 序列化为 ``{line_id, warning}``
    的 dict 写入 ``GenerationTask.result``，供前端任务面板展示。
    """

    chapter_id: str
    decisions: list[DurationDecision] = field(default_factory=list)
    holds: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DurationEstimator
# ---------------------------------------------------------------------------


class DurationEstimator:
    """估算 TTS 输出时长的纯计算模块（无 LLM / DB 依赖）。

    设计要点:
        - 中文按字符计数，英文按单词计数后折成 5 chars/word 等效；
        - 速率乘以 ``speed * voice_pack.default_speed``，等价于
          “effective chars-per-sec”；
        - 边界：空文本返回 0ms，避免在主流程里再 if/else。
    """

    @staticmethod
    def detect_language(text: str) -> Literal["zh", "en", "mixed"]:
        """简易语言检测：基于 unicode 范围。

        逻辑:
            - 任一字符落在 CJK 区段 ``\\u4e00-\\u9fff`` 视为中文字符；
            - ASCII 字母视为英文字符；
            - 同时含两类 → mixed；仅含中文 → zh；其它（含纯英文 / 纯空文本）→ en。

        参数:
            text: 任意 UTF-8 字符串。

        返回:
            ``"zh"`` / ``"en"`` / ``"mixed"`` 之一。
        """

        zh_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        en_count = sum(1 for c in text if c.isascii() and c.isalpha())
        if zh_count > 0 and en_count > 0:
            return "mixed"
        if zh_count > 0:
            return "zh"
        return "en"

    @classmethod
    def estimate(
        cls,
        *,
        text: str,
        line_mode: DialogueLineMode,
        voice_pack: VoicePack,
        speed: float = 1.0,
    ) -> DurationEstimate:
        """估算文本在指定音色下的 TTS 输出时长（毫秒）。

        参数:
            text: 待合成文本。
            line_mode: ``ShotDialogLine.line_mode``；voice_over 走更慢的
                旁白速率。
            voice_pack: 音色包；``default_speed`` 与 ``speed`` 相乘进入
                effective_rate。
            speed: 用户/规划器指定的额外语速倍率，缺省 1.0。

        返回:
            :class:`DurationEstimate`，``estimated_ms`` 已向上取整避免
            截断后小于真实输出长度。
        """

        lang = cls.detect_language(text)
        base_rate, char_count = cls._language_rate(text, lang, line_mode)

        # effective_rate 已经把 default_speed 与 speed 全部并入；
        # 后续主流程靠 (chars_per_sec / 当前 speed 倍率) 反推 base_rate。
        effective_rate = base_rate * speed * float(voice_pack.default_speed or 1.0)

        if char_count <= 0 or effective_rate <= 0:
            ms = 0
        else:
            ms = int(math.ceil(char_count / effective_rate * 1000))

        return DurationEstimate(
            text=text,
            language=lang,
            voice_pack_id=voice_pack.id,
            base_speed=speed * float(voice_pack.default_speed or 1.0),
            estimated_ms=ms,
            char_count=char_count,
            chars_per_sec=effective_rate,
        )

    @staticmethod
    def _language_rate(
        text: str,
        lang: Literal["zh", "en", "mixed"],
        line_mode: DialogueLineMode,
    ) -> tuple[float, int]:
        """根据语言族 + 模式选择 base_rate 并计数有效字符。

        返回 ``(base_rate, char_count)``。
        """

        if lang == "zh":
            base_rate = (
                ZH_CHARS_PER_SEC_NARRATION
                if line_mode == DialogueLineMode.voice_over
                else ZH_CHARS_PER_SEC_DIALOG
            )
            # 仅计 CJK 字符（剔除空格 / 标点对时长的低权影响）。
            char_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            return base_rate, char_count

        if lang == "en":
            # 英文每词约 5 字符；EN_WORDS_PER_SEC * 5 即 chars/sec 速率。
            base_rate = EN_WORDS_PER_SEC * 5.0
            char_count = len(text.replace(" ", ""))
            return base_rate, char_count

        # mixed：取中英两侧的算术均值，避免单侧失真。
        base_rate = (ZH_CHARS_PER_SEC_DIALOG + EN_WORDS_PER_SEC * 5.0) / 2.0
        char_count = sum(1 for c in text if not c.isspace())
        return base_rate, char_count


# ---------------------------------------------------------------------------
# ChapterAvPlanner
# ---------------------------------------------------------------------------


class ChapterAvPlanner:
    """章节级 AV plan 编排器。

    构造参数:
        rewriter_invoker: ``async (db, *, original_text, target_chars,
            line_mode) -> rewritten_text``；用于在 ``llm_rewrite`` 分支
            产出新文本。把它做成依赖注入而非直接吃 ``DurationRewriterAgent``，
            是为了让本类完全可脱离 LLM 与 DB 单测。
    """

    def __init__(self, *, rewriter_invoker: RewriterInvoker) -> None:
        """初始化规划器；``rewriter_invoker`` 必须是异步可调用对象。"""

        self._rewriter_invoker = rewriter_invoker

    async def plan_dialog_line(
        self,
        *,
        db: object,
        line: ShotDialogLine,
        shot_duration_ms: int,
        voice_pack: VoicePack,
        audio_strategy: AudioStrategy = AudioStrategy.silent_with_tts,
    ) -> DurationDecision:
        """对单条 ``ShotDialogLine`` 执行完整 Decision F 决策。

        参数:
            db: 透传给 ``rewriter_invoker`` 的 session（本类自身不读写 DB）。
            line: 待规划的对白行；只读 ``text`` / ``line_mode`` / ``id``。
            shot_duration_ms: 镜头时长（毫秒），即决策目标。
            voice_pack: 用于估算的音色包；``default_speed`` 影响估算结果。
            audio_strategy: 镜头音频策略（P3 W17 收尾，Decision D 修订）。
                默认 ``silent_with_tts`` 走完整 Decision F；若为 ``keep_native``
                则整树跳过，直接返回 ``action="skip_native"`` 决策——原文落库、
                speed=1.0、estimated_ms=shot_duration_ms 占位（真实时长由
                视频生成模型自带原音决定，下游 ASR 反推字幕时再校准）。

        返回:
            :class:`DurationDecision`，其中 ``action`` 表明落点分支。
        """

        if audio_strategy == AudioStrategy.keep_native:
            return DurationDecision(
                dialog_line_id=int(line.id),
                action="skip_native",
                original_text=line.text,
                final_text=line.text,
                suggested_speed=1.0,
                target_duration_ms=shot_duration_ms,
                estimated_ms=shot_duration_ms,
            )

        # Step 1: ESTIMATE。
        estimate = DurationEstimator.estimate(
            text=line.text,
            line_mode=line.line_mode,
            voice_pack=voice_pack,
            speed=1.0,
        )

        # Step 2: COMPARE。
        if self._within_threshold(estimate.estimated_ms, shot_duration_ms):
            return DurationDecision(
                dialog_line_id=int(line.id),
                action="accept",
                original_text=line.text,
                final_text=line.text,
                suggested_speed=1.0,
                target_duration_ms=shot_duration_ms,
                estimated_ms=estimate.estimated_ms,
            )

        # Step 3a: SPEED_ADJUST。
        speed_decision = self._try_speed_adjust(
            line=line,
            voice_pack=voice_pack,
            estimate=estimate,
            shot_duration_ms=shot_duration_ms,
        )
        if speed_decision is not None:
            return speed_decision

        # Step 3b: LLM_REWRITE（最多 MAX_REWRITE_ATTEMPTS 次）。
        rewrite_decision = await self._try_llm_rewrite(
            db=db,
            line=line,
            voice_pack=voice_pack,
            shot_duration_ms=shot_duration_ms,
            initial_estimate=estimate,
        )
        return rewrite_decision

    # ------------------------------------------------------------------
    # 决策树分支辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _within_threshold(estimated_ms: int, shot_duration_ms: int) -> bool:
        """``|est-target| / target ≤ MISMATCH_THRESHOLD`` 时视为可 accept。"""

        if shot_duration_ms <= 0:
            return False
        ratio = abs(estimated_ms - shot_duration_ms) / shot_duration_ms
        return ratio <= MISMATCH_THRESHOLD

    def _try_speed_adjust(
        self,
        *,
        line: ShotDialogLine,
        voice_pack: VoicePack,
        estimate: DurationEstimate,
        shot_duration_ms: int,
    ) -> DurationDecision | None:
        """在 ``[SPEED_MIN, SPEED_MAX]`` 区间求一次 clamp 后的 estimate。

        逻辑：
            - 想要 ``estimated_ms == shot_duration_ms``，
              即 ``effective_rate = char_count / (shot_duration_ms / 1000)``。
            - 当前 effective_rate 在 ``speed=1.0`` 下等于 ``estimate.chars_per_sec``。
            - 因此 ``ideal_speed = target_rate / chars_per_sec``。
            - clamp 到 ``[SPEED_MIN, SPEED_MAX]`` 后重新估算；落入阈值即返回。
        """

        if estimate.chars_per_sec <= 0 or estimate.char_count <= 0:
            return None
        target_rate = estimate.char_count / (shot_duration_ms / 1000.0)
        ideal_speed = target_rate / estimate.chars_per_sec
        clamped_speed = max(SPEED_MIN, min(SPEED_MAX, ideal_speed))

        adjusted = DurationEstimator.estimate(
            text=line.text,
            line_mode=line.line_mode,
            voice_pack=voice_pack,
            speed=clamped_speed,
        )
        if not self._within_threshold(adjusted.estimated_ms, shot_duration_ms):
            return None
        return DurationDecision(
            dialog_line_id=int(line.id),
            action="speed_adjust",
            original_text=line.text,
            final_text=line.text,
            suggested_speed=clamped_speed,
            target_duration_ms=shot_duration_ms,
            estimated_ms=adjusted.estimated_ms,
        )

    async def _try_llm_rewrite(
        self,
        *,
        db: object,
        line: ShotDialogLine,
        voice_pack: VoicePack,
        shot_duration_ms: int,
        initial_estimate: DurationEstimate,
    ) -> DurationDecision:
        """LLM 改写循环：最多 ``MAX_REWRITE_ATTEMPTS`` 次；仍未收敛 → hold。"""

        target_chars = self._target_char_count(
            shot_duration_ms=shot_duration_ms, line_mode=line.line_mode
        )
        current_text = line.text
        last_estimate = initial_estimate
        for attempt in range(1, MAX_REWRITE_ATTEMPTS + 1):
            rewritten = await self._rewriter_invoker(
                db,
                original_text=current_text,
                target_chars=target_chars,
                line_mode=line.line_mode,
            )
            re_estimate = DurationEstimator.estimate(
                text=rewritten,
                line_mode=line.line_mode,
                voice_pack=voice_pack,
                speed=1.0,
            )
            last_estimate = re_estimate
            if self._within_threshold(re_estimate.estimated_ms, shot_duration_ms):
                return DurationDecision(
                    dialog_line_id=int(line.id),
                    action="llm_rewrite",
                    original_text=line.text,
                    final_text=rewritten,
                    suggested_speed=1.0,
                    target_duration_ms=shot_duration_ms,
                    estimated_ms=re_estimate.estimated_ms,
                    rewrite_attempts=attempt,
                )
            current_text = rewritten  # 仍超阈值，下一轮基于更短的版本继续收敛。

        # Step 3c: HOLD。
        warning = (
            f"连续 {MAX_REWRITE_ATTEMPTS} 次 LLM 改写仍未收敛到 ±"
            f"{int(MISMATCH_THRESHOLD * 100)}% 阈值，需要人工介入"
        )
        return DurationDecision(
            dialog_line_id=int(line.id),
            action="hold",
            original_text=line.text,
            final_text=current_text,
            suggested_speed=1.0,
            target_duration_ms=shot_duration_ms,
            estimated_ms=last_estimate.estimated_ms,
            rewrite_attempts=MAX_REWRITE_ATTEMPTS,
            warning=warning,
        )

    @staticmethod
    def _target_char_count(
        *, shot_duration_ms: int, line_mode: DialogueLineMode
    ) -> int:
        """根据 ``line_mode`` 决定目标字数上限。

        - ``voice_over``：``≤ 3 × duration_sec``；
        - 其它（dialog / off_screen / phone）：``≤ 4 × duration_sec``。
        """

        rate = (
            ZH_CHARS_PER_SEC_NARRATION
            if line_mode == DialogueLineMode.voice_over
            else ZH_CHARS_PER_SEC_DIALOG
        )
        return max(1, int(shot_duration_ms / 1000.0 * rate))


__all__ = [
    "ChapterAvPlanResult",
    "ChapterAvPlanner",
    "DecisionAction",
    "DurationDecision",
    "DurationEstimate",
    "DurationEstimator",
    "EN_WORDS_PER_SEC",
    "MAX_REWRITE_ATTEMPTS",
    "MISMATCH_THRESHOLD",
    "RewriterInvoker",
    "SPEED_MAX",
    "SPEED_MIN",
    "ZH_CHARS_PER_SEC_DIALOG",
    "ZH_CHARS_PER_SEC_NARRATION",
]
