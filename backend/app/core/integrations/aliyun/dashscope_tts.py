"""阿里云百炼 DashScope CosyVoice TTS WebSocket 适配 + Paraformer-v2 ASR fallback。

CosyVoice 仅支持 WebSocket 协议（官方文档明确说明 not HTTP REST），因此本模块基于
原生 ``websockets`` 库（已在 backend venv，版本 16.0）实现客户端三段式握手：

    1. ``run-task``     首帧：声明 model/voice/parameters，等待 ``task-started``
    2. ``continue-task`` 文本帧：可重复，每次 ≤ 20k 字符，整 session ≤ 200k
    3. ``finish-task``  结束帧：触发服务端最终落盘并广播 ``task-finished``

服务端按事件类型推送（``payload.output.type``）：

    - ``task-started`` ── 同步信号，必须先收到再发文本
    - ``sentence-begin`` ── 词级时间戳（payload.output.sentence.words）
    - ``sentence-synthesis`` ── 紧跟一帧二进制音频
    - ``sentence-end`` ── 句尾用量
    - ``task-finished`` ── 终止
    - ``task-failed`` ── 终止 + 错误码/信息

签名形状对齐 ``DashScopeVideoApiAdapter``：``async def synthesize(*, cfg, input_, timeout_s)``。

CosyVoice 复刻音色（user-cloned voice）等场景词级时间戳缺失时，提供
``estimate_audio_via_asr`` 调 Paraformer-v2 异步 ASR 兜底（mirror dashscope_videos
的 submit + poll + result-fetch HTTP 三段式）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.tts import TtsRequest, TtsWordTimestamp

logger = logging.getLogger(__name__)


# WebSocket / REST 端点常量（不可被 cfg.base_url 覆盖：CosyVoice 仅此一条公网入口）。
_DASHSCOPE_TTS_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
_DASHSCOPE_PARAFORMER_BASE = "https://dashscope.aliyuncs.com"

# 业务侧默认值（与 P3 W17 vp-default 对齐）。
_DEFAULT_TTS_MODEL = "cosyvoice-v2"
_DEFAULT_VOLUME = 50
_DEFAULT_PITCH = 1.0

# Paraformer-v2 任务轮询节流（保持与 dashscope_videos 一致的 2s 节奏）。
_PARAFORMER_POLL_INTERVAL_S = 2.0


# --------------------------------------------------------------------------- #
# 报文构造                                                                       #
# --------------------------------------------------------------------------- #


def _build_run_task_message(task_id: str, request: TtsRequest) -> dict[str, Any]:
    """构造 CosyVoice run-task 首帧。

    严格按照官方协议字段映射：``parameters.voice`` 必须是 provider_voice_id（如
    ``longxiaochun_v2``），不是业务侧 voice_pack_id。``rate`` 字段承载语速倍率。
    """
    parameters: dict[str, Any] = {
        "text_type": "PlainText",
        "voice": request.provider_voice_id,
        "format": request.audio_format,
        "sample_rate": int(request.sample_rate),
        "volume": _DEFAULT_VOLUME,
        "rate": float(request.speed),
        "pitch": _DEFAULT_PITCH,
        "word_timestamp_enabled": bool(request.enable_word_timestamps),
        "language_hints": list(request.language_hints) if request.language_hints else ["zh"],
    }
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "tts",
            "function": "SpeechSynthesizer",
            "model": _DEFAULT_TTS_MODEL,
            "parameters": parameters,
            "input": {},
        },
    }


def _build_continue_task_message(task_id: str, text: str) -> dict[str, Any]:
    """continue-task 帧：携带要合成的文本，单帧 ≤ 20k 字符（业务侧已切片）。"""
    return {
        "header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {"text": text}},
    }


def _build_finish_task_message(task_id: str) -> dict[str, Any]:
    """finish-task 帧：声明文本输入完毕，等待服务端 task-finished。"""
    return {
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {}},
    }


# --------------------------------------------------------------------------- #
# 服务端事件解析                                                                 #
# --------------------------------------------------------------------------- #


def _extract_event_type(message: dict[str, Any]) -> str | None:
    """从服务端 JSON 消息提取事件类型。

    协议优先取 ``payload.output.type``（CosyVoice 当前格式），fallback 到
    ``header.event``（部分实现仅在 header 携带）。两处皆不存在返回 None。
    """
    payload = message.get("payload")
    if isinstance(payload, dict):
        output = payload.get("output")
        if isinstance(output, dict):
            t = output.get("type")
            if isinstance(t, str) and t:
                return t
    header = message.get("header")
    if isinstance(header, dict):
        ev = header.get("event")
        if isinstance(ev, str) and ev:
            return ev
    return None


def _extract_sentence_words(message: dict[str, Any]) -> list[TtsWordTimestamp]:
    """从 sentence-begin 事件提取词级时间戳。

    DashScope 按毫秒返回 begin_time / end_time；这里直接落到契约的 begin_ms / end_ms。
    任意单词解析失败均跳过，绝不让一两个坏字段中断整段合成。
    """
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return []
    output = payload.get("output")
    if not isinstance(output, dict):
        return []
    sentence = output.get("sentence")
    if not isinstance(sentence, dict):
        return []
    words = sentence.get("words")
    if not isinstance(words, list):
        return []
    out: list[TtsWordTimestamp] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        text_value = word.get("text")
        if not isinstance(text_value, str) or not text_value:
            continue
        try:
            begin_ms = int(word.get("begin_time") or 0)
            end_ms = int(word.get("end_time") or 0)
        except (TypeError, ValueError):
            continue
        out.append(TtsWordTimestamp(text=text_value, begin_ms=begin_ms, end_ms=end_ms))
    return out


def _extract_failure_detail(message: dict[str, Any]) -> str:
    """task-failed 事件时拼接 ``code: message`` 给上层抛异常用。"""
    payload = message.get("payload")
    if isinstance(payload, dict):
        output = payload.get("output")
        if isinstance(output, dict):
            code = output.get("code")
            msg = output.get("message")
            parts = [str(item) for item in (code, msg) if item is not None and str(item).strip()]
            if parts:
                return ": ".join(parts) if len(parts) > 1 else parts[0]
    header = message.get("header")
    if isinstance(header, dict):
        code = header.get("error_code") or header.get("code")
        msg = header.get("error_message") or header.get("message")
        parts = [str(item) for item in (code, msg) if item is not None and str(item).strip()]
        if parts:
            return ": ".join(parts) if len(parts) > 1 else parts[0]
    return "DashScope CosyVoice task failed"


# --------------------------------------------------------------------------- #
# Paraformer-v2 transcription 解析                                              #
# --------------------------------------------------------------------------- #


def _parse_paraformer_transcription(data: dict[str, Any]) -> list[TtsWordTimestamp]:
    """从 Paraformer-v2 transcription_url JSON 提取词级时间戳。

    结构：``transcripts[].sentences[].words[].begin_time / end_time``（毫秒）。
    """
    out: list[TtsWordTimestamp] = []
    if not isinstance(data, dict):
        return out
    transcripts = data.get("transcripts")
    if not isinstance(transcripts, list):
        return out
    for transcript in transcripts:
        if not isinstance(transcript, dict):
            continue
        sentences = transcript.get("sentences")
        if not isinstance(sentences, list):
            continue
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            words = sentence.get("words")
            if not isinstance(words, list):
                continue
            for word in words:
                if not isinstance(word, dict):
                    continue
                text_value = word.get("text")
                if not isinstance(text_value, str) or not text_value:
                    continue
                try:
                    begin_ms = int(word.get("begin_time") or 0)
                    end_ms = int(word.get("end_time") or 0)
                except (TypeError, ValueError):
                    continue
                out.append(TtsWordTimestamp(text=text_value, begin_ms=begin_ms, end_ms=end_ms))
    return out


# --------------------------------------------------------------------------- #
# Adapter                                                                       #
# --------------------------------------------------------------------------- #


class DashScopeTtsApiAdapter:
    """DashScope CosyVoice TTS：WebSocket 全双工合成 + Paraformer-v2 兜底 ASR。

    与 ``DashScopeVideoApiAdapter`` 保持接口形状一致：
    ``async def synthesize(*, cfg, input_, timeout_s) -> tuple[bytes, list[TtsWordTimestamp]]``
    及异步 ASR 兜底 ``estimate_audio_via_asr``。
    """

    async def synthesize(
        self,
        *,
        cfg: ProviderConfig,
        input_: TtsRequest,
        timeout_s: float = 120.0,
    ) -> tuple[bytes, list[TtsWordTimestamp]]:
        """单次完整 WebSocket 合成。

        发送 run-task → 等 task-started → 发 continue-task + finish-task → 边收音频
        二进制帧边收 sentence-begin 词时间戳 → 收到 task-finished 收尾。任意阶段
        超过 ``timeout_s`` 总挂钟，整体抛 ``RuntimeError``。

        :param cfg: 包含 DashScope api_key 的供应商配置（base_url 仅 ASR 用，
            WebSocket URL 由常量决定）。
        :param input_: TtsRequest（text/voice/speed/format/...）。
        :param timeout_s: 总挂钟超时；单次内 inactivity-23s 由 server-side ping 控制，
            ``websockets`` 库会自动维持心跳。
        :returns: ``(audio_bytes, word_timestamps)``。前者按二进制帧到达顺序拼接；
            后者来自所有 sentence-begin 事件。
        :raises RuntimeError: 服务端 task-failed、超时或 WebSocket 异常。
        """
        try:
            import websockets  # noqa: WPS433 - 延迟导入，与 dashscope_videos 风格一致
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets is required for DashScope CosyVoice TTS") from exc

        task_id = uuid.uuid4().hex
        run_msg = _build_run_task_message(task_id, input_)
        continue_msg = _build_continue_task_message(task_id, input_.text)
        finish_msg = _build_finish_task_message(task_id)

        audio_buffer = bytearray()
        word_timestamps: list[TtsWordTimestamp] = []

        async def _run() -> None:
            async with websockets.connect(
                _DASHSCOPE_TTS_WS_URL,
                additional_headers={"Authorization": f"Bearer {cfg.api_key}"},
            ) as ws:
                await ws.send(json.dumps(run_msg))
                logger.debug("DashScope TTS: sent run-task task_id=%s", task_id)
                await self._consume_events(
                    ws=ws,
                    task_id=task_id,
                    continue_msg=continue_msg,
                    finish_msg=finish_msg,
                    audio_buffer=audio_buffer,
                    word_timestamps=word_timestamps,
                )

        try:
            await asyncio.wait_for(_run(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"DashScope CosyVoice TTS timed out after {timeout_s:.1f}s "
                f"(task_id={task_id})"
            ) from exc

        return bytes(audio_buffer), word_timestamps

    async def _consume_events(
        self,
        *,
        ws: Any,
        task_id: str,
        continue_msg: dict[str, Any],
        finish_msg: dict[str, Any],
        audio_buffer: bytearray,
        word_timestamps: list[TtsWordTimestamp],
    ) -> None:
        """事件循环：拆分到独立方法降低 ``synthesize`` 复杂度。"""
        text_sent = False
        while True:
            frame = await ws.recv()
            if isinstance(frame, (bytes, bytearray)):
                audio_buffer.extend(frame)
                continue
            try:
                data = json.loads(frame)
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.debug("DashScope TTS: dropping non-JSON text frame (task_id=%s)", task_id)
                continue
            if not isinstance(data, dict):
                continue
            event = _extract_event_type(data)
            logger.debug("DashScope TTS: event=%s task_id=%s", event, task_id)
            if event == "task-started":
                if not text_sent:
                    await ws.send(json.dumps(continue_msg))
                    await ws.send(json.dumps(finish_msg))
                    text_sent = True
                continue
            if event == "sentence-begin":
                word_timestamps.extend(_extract_sentence_words(data))
                continue
            if event in ("sentence-synthesis", "sentence-end", "result-generated"):
                continue
            if event == "task-finished":
                return
            if event == "task-failed":
                raise RuntimeError(_extract_failure_detail(data))
            logger.debug(
                "DashScope TTS: unhandled event %r ignored (task_id=%s)",
                event,
                task_id,
            )

    async def estimate_audio_via_asr(
        self,
        *,
        cfg: ProviderConfig,
        audio_url: str,
        timeout_s: float = 600.0,
    ) -> list[TtsWordTimestamp]:
        """Paraformer-v2 异步 ASR 兜底：基于已生成音频反推词级时间戳。

        典型场景：用户上传复刻音色，CosyVoice 不返回 word_timestamp 时改走 ASR
        提取词时间戳。流程 mirror ``DashScopeVideoApiAdapter`` 的 submit → poll →
        fetch transcription_url 三段：

            POST /api/v1/services/audio/asr/transcription   (X-DashScope-Async)
            POST /api/v1/tasks/{task_id}                    (轮询)
            GET  <transcription_url>                        (拉结果)
        """
        try:
            import httpx  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for paraformer ASR") from exc

        origin = (cfg.base_url or _DASHSCOPE_PARAFORMER_BASE).rstrip("/")
        # cfg.base_url 通常指向 OpenAI 兼容 endpoint（如 .../compatible-mode/v1），
        # 与 DashScope 原生 /api/v1 不互通：只要 origin 不是 dashscope.aliyuncs.com 顶级，
        # 仍然回退到 _DASHSCOPE_PARAFORMER_BASE 以避免 404。
        if "dashscope.aliyuncs.com" not in origin:
            origin = _DASHSCOPE_PARAFORMER_BASE
        submit_url = f"{origin}/api/v1/services/audio/asr/transcription"
        auth_headers = {"Authorization": f"Bearer {cfg.api_key}"}
        submit_headers = {
            **auth_headers,
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        body = {
            "model": "paraformer-v2",
            "input": {"file_urls": [audio_url]},
            "parameters": {
                "channel_id": [0],
                "language_hints": ["zh", "en"],
                "timestamp_alignment_enabled": True,
                "disfluency_removal_enabled": False,
            },
        }

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            submit_resp = await client.post(submit_url, headers=submit_headers, json=body)
            submit_resp.raise_for_status()
            submit_data = submit_resp.json()
            submit_output = submit_data.get("output")
            output: dict[str, Any] = submit_output if isinstance(submit_output, dict) else {}
            task_id = str(output.get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError(
                    f"DashScope Paraformer submit missing task_id: {submit_data!r}"
                )

            poll_url = f"{origin}/api/v1/tasks/{task_id}"
            transcription_url: str | None = None
            poll_meta: dict[str, Any] = {}
            while True:
                poll_resp = await client.get(poll_url, headers=auth_headers)
                poll_resp.raise_for_status()
                poll_meta = poll_resp.json()
                raw_output = poll_meta.get("output") if isinstance(poll_meta, dict) else None
                poll_output: dict[str, Any] = raw_output if isinstance(raw_output, dict) else {}
                status = str(poll_output.get("task_status") or "").upper()
                if status == "SUCCEEDED":
                    results = poll_output.get("results")
                    if isinstance(results, list) and results and isinstance(results[0], dict):
                        transcription_url = (
                            results[0].get("transcription_url")
                            or results[0].get("output_url")
                        )
                    break
                if status in ("FAILED", "CANCELED", "CANCELLED"):
                    raise RuntimeError(
                        f"DashScope Paraformer task {status.lower()}: {poll_meta!r}"
                    )
                await asyncio.sleep(_PARAFORMER_POLL_INTERVAL_S)

            if not transcription_url:
                raise RuntimeError(
                    f"DashScope Paraformer no transcription_url: {poll_meta!r}"
                )

            tr_resp = await client.get(transcription_url)
            tr_resp.raise_for_status()
            return _parse_paraformer_transcription(tr_resp.json())
