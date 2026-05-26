"""P3 W17 T17-6：DashScope CosyVoice TTS WebSocket 适配 + Paraformer-v2 ASR fallback 测试。

CosyVoice 仅支持 WebSocket（无 HTTP REST 接口）。本套测试通过 mock `websockets.connect`
模拟服务端事件流，覆盖：

- WebSocket URL 常量
- run-task 报文形状（model/voice/word_timestamp_enabled）
- 完整事件流：task-started → continue-task → sentence-begin (3 词) → 二进制帧 → sentence-end → task-finished
- 二进制音频帧累积
- 词级时间戳解析（TtsWordTimestamp 实例，begin_ms/end_ms）
- task-failed 抛 RuntimeError 携带 code+message
- 超时包装为 RuntimeError
- Paraformer-v2 ASR：submit body 形状、poll URL 模式、transcription 解析
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.tts import TtsRequest, TtsWordTimestamp
from app.core.integrations.aliyun import dashscope_tts


# --------------------------------------------------------------------------- #
# Fake WebSocket: 服务器侧脚本驱动的 mock，记录客户端发送的报文，按脚本回放消息。   #
# --------------------------------------------------------------------------- #


class _FakeServerWebSocket:
    """模拟 dashscope WebSocket 服务端：脚本驱动收发。

    - server_script: "服务端推送帧"列表，元素可以是：
        - dict      → 自动 JSON 序列化为文本帧
        - str       → 文本帧
        - bytes     → 二进制帧
    - sent: 客户端发送的报文（解析后的 dict 或原始 bytes）

    脚本与客户端 send/recv 顺序天然由协议状态机驱动（adapter 收到 task-started
    后才会下发 continue-task/finish-task），无需额外同步原语。
    """

    def __init__(self, server_script: list[Any]) -> None:
        self._script = list(server_script)
        self.sent: list[Any] = []

    async def send(self, frame: Any) -> None:
        if isinstance(frame, (bytes, bytearray)):
            self.sent.append(bytes(frame))
        else:
            try:
                self.sent.append(json.loads(frame))
            except (TypeError, json.JSONDecodeError):
                self.sent.append(frame)

    async def recv(self) -> Any:
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, dict):
                return json.dumps(item)
            return item
        # 脚本耗尽 → 阻塞，模拟服务端断流（用于 test_timeout_wraps_into_runtime_error）
        await asyncio.sleep(3600)
        raise RuntimeError("script exhausted")  # pragma: no cover

    async def close(self) -> None:  # pragma: no cover - websockets ctx auto closes
        return None


class _FakeWebSocketsConnect:
    """模拟 `websockets.connect(...)` 返回的异步上下文。"""

    def __init__(self, fake_ws: _FakeServerWebSocket, captured: dict[str, Any]) -> None:
        self._fake_ws = fake_ws
        self._captured = captured

    async def __aenter__(self) -> _FakeServerWebSocket:
        return self._fake_ws

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _patch_websockets_connect(
    monkeypatch: pytest.MonkeyPatch,
    server_script: list[Any],
) -> tuple[_FakeServerWebSocket, dict[str, Any]]:
    """将 `dashscope_tts` 模块内部的 websockets.connect 替换为脚本驱动 mock。"""
    fake_ws = _FakeServerWebSocket(server_script)
    captured: dict[str, Any] = {}

    def _fake_connect(url: str, **kwargs: Any) -> _FakeWebSocketsConnect:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeWebSocketsConnect(fake_ws, captured)

    import websockets  # noqa: WPS433 - mock 时机

    monkeypatch.setattr(websockets, "connect", _fake_connect)
    return fake_ws, captured


# --------------------------------------------------------------------------- #
# 工具：构造默认 cfg / request / 服务器脚本                                     #
# --------------------------------------------------------------------------- #


def _make_cfg() -> ProviderConfig:
    return ProviderConfig(
        provider="aliyun_bailian",
        api_key="sk-test-key",
        base_url=None,
    )


def _make_request(text: str = "你好世界") -> TtsRequest:
    return TtsRequest(
        text=text,
        voice_pack_id="cosyvoice_v2_longxiaochun",
        provider_voice_id="longxiaochun_v2",
        speed=1.0,
        audio_format="mp3",
    )


def _success_script(audio_bytes: bytes = b"\x01\x02\x03\x04") -> list[Any]:
    """完整成功流：task-started → 等客户端 send → sentence-begin(3 词) → bin → sentence-end → task-finished。"""
    return [
        {
            "header": {"task_id": "tid", "event": "task-started"},
            "payload": {"output": {"type": "task-started"}},
        },
        {
            "header": {"task_id": "tid", "event": "result-generated"},
            "payload": {
                "output": {
                    "type": "sentence-begin",
                    "sentence": {
                        "words": [
                            {"text": "你", "begin_time": 0, "end_time": 200, "begin_index": 0, "end_index": 1},
                            {"text": "好", "begin_time": 200, "end_time": 400, "begin_index": 1, "end_index": 2},
                            {"text": "世界", "begin_time": 400, "end_time": 800, "begin_index": 2, "end_index": 4},
                        ],
                    },
                },
            },
        },
        {
            "header": {"task_id": "tid", "event": "result-generated"},
            "payload": {"output": {"type": "sentence-synthesis"}},
        },
        audio_bytes,
        {
            "header": {"task_id": "tid", "event": "result-generated"},
            "payload": {"output": {"type": "sentence-end", "usage": {"characters": 4}}},
        },
        {
            "header": {"task_id": "tid", "event": "task-finished"},
            "payload": {"output": {"type": "task-finished"}},
        },
    ]


# --------------------------------------------------------------------------- #
# 测试                                                                          #
# --------------------------------------------------------------------------- #


def test_websocket_url_constant() -> None:
    """WebSocket URL 必须是官方 dashscope api-ws/v1/inference。"""
    assert (
        dashscope_tts._DASHSCOPE_TTS_WS_URL  # noqa: SLF001 - 测试常量
        == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    )


def test_paraformer_base_url_constant() -> None:
    """Paraformer-v2 base URL 必须是 dashscope.aliyuncs.com 根。"""
    assert (
        dashscope_tts._DASHSCOPE_PARAFORMER_BASE  # noqa: SLF001
        == "https://dashscope.aliyuncs.com"
    )


@pytest.mark.asyncio
async def test_run_task_body_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """run-task 报文必须含 model=cosyvoice-v2、parameters.voice、word_timestamp_enabled=true。"""
    fake_ws, captured = _patch_websockets_connect(monkeypatch, _success_script())

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    audio, words = await adapter.synthesize(
        cfg=_make_cfg(),
        input_=_make_request(),
        timeout_s=5.0,
    )

    # 第 1 帧 = run-task
    assert isinstance(fake_ws.sent[0], dict)
    run_msg = fake_ws.sent[0]
    assert run_msg["header"]["action"] == "run-task"
    assert run_msg["header"]["streaming"] == "duplex"
    assert len(run_msg["header"]["task_id"]) == 32  # uuid.uuid4().hex
    assert run_msg["payload"]["task_group"] == "audio"
    assert run_msg["payload"]["task"] == "tts"
    assert run_msg["payload"]["function"] == "SpeechSynthesizer"
    assert run_msg["payload"]["model"] == "cosyvoice-v2"
    params = run_msg["payload"]["parameters"]
    assert params["voice"] == "longxiaochun_v2"
    assert params["word_timestamp_enabled"] is True
    assert params["format"] == "mp3"
    assert params["text_type"] == "PlainText"
    assert "language_hints" in params
    # Authorization 通过 additional_headers 传递（注意：不能是 extra_headers）
    assert captured["kwargs"]["additional_headers"]["Authorization"] == "Bearer sk-test-key"
    # 后续未抛异常即 OK
    assert isinstance(audio, bytes)
    assert isinstance(words, list)


@pytest.mark.asyncio
async def test_continue_and_finish_task_sent_after_started(monkeypatch: pytest.MonkeyPatch) -> None:
    """收到 task-started 后必须先发 continue-task(text)，再发 finish-task。"""
    fake_ws, _captured = _patch_websockets_connect(monkeypatch, _success_script())

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(text="测试文本"), timeout_s=5.0)

    actions = [
        item["header"]["action"]
        for item in fake_ws.sent
        if isinstance(item, dict)
    ]
    assert actions == ["run-task", "continue-task", "finish-task"]
    # continue-task 携带文本
    cont = fake_ws.sent[1]
    assert cont["payload"]["input"]["text"] == "测试文本"
    # finish-task 空 input
    fin = fake_ws.sent[2]
    assert fin["payload"]["input"] == {}
    # 同一 task_id 贯穿 3 条
    tids = {item["header"]["task_id"] for item in fake_ws.sent if isinstance(item, dict)}
    assert len(tids) == 1


@pytest.mark.asyncio
async def test_audio_bytes_and_word_timestamps_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    """二进制帧累积为 audio_bytes；sentence-begin 转 TtsWordTimestamp。"""
    audio_chunk = b"\xff\xfb\x90\x44test-audio-chunk"
    _patch_websockets_connect(monkeypatch, _success_script(audio_bytes=audio_chunk))

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    audio, words = await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(), timeout_s=5.0)

    assert audio == audio_chunk
    assert len(words) == 3
    assert all(isinstance(w, TtsWordTimestamp) for w in words)
    assert words[0].text == "你"
    assert words[0].begin_ms == 0
    assert words[0].end_ms == 200
    assert words[2].text == "世界"
    assert words[2].end_ms == 800


@pytest.mark.asyncio
async def test_multiple_binary_frames_concatenated(monkeypatch: pytest.MonkeyPatch) -> None:
    """多个二进制帧应按接收顺序拼接。"""
    script: list[Any] = [
        {"header": {"event": "task-started"}, "payload": {"output": {"type": "task-started"}}},
        {"header": {"event": "result-generated"}, "payload": {"output": {"type": "sentence-synthesis"}}},
        b"AAAA",
        {"header": {"event": "result-generated"}, "payload": {"output": {"type": "sentence-synthesis"}}},
        b"BBBB",
        {"header": {"event": "result-generated"}, "payload": {"output": {"type": "sentence-synthesis"}}},
        b"CCCC",
        {"header": {"event": "task-finished"}, "payload": {"output": {"type": "task-finished"}}},
    ]
    _patch_websockets_connect(monkeypatch, script)

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    audio, _ = await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(), timeout_s=5.0)
    assert audio == b"AAAABBBBCCCC"


@pytest.mark.asyncio
async def test_task_failed_raises_with_code_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """task-failed 必须抛 RuntimeError，并带上 code: message。"""
    script: list[Any] = [
        {"header": {"event": "task-started"}, "payload": {"output": {"type": "task-started"}}},
        {
            "header": {"event": "task-failed"},
            "payload": {
                "output": {
                    "type": "task-failed",
                    "code": "QuotaExceeded",
                    "message": "Daily TTS quota exceeded",
                },
            },
        },
    ]
    _patch_websockets_connect(monkeypatch, script)

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(), timeout_s=5.0)
    msg = str(exc_info.value)
    assert "QuotaExceeded" in msg
    assert "Daily TTS quota exceeded" in msg


@pytest.mark.asyncio
async def test_timeout_wraps_into_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """超过 timeout_s 必须抛 RuntimeError（asyncio.TimeoutError 包装）。"""
    # 服务端永远不响应：脚本只 yield 一帧 task-started 都没有，直接挂起
    script: list[Any] = []
    _patch_websockets_connect(monkeypatch, script)

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(), timeout_s=0.1)
    assert "timed out" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_unknown_event_is_logged_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """收到未知事件不应该抛错；继续等待 task-finished。"""
    script: list[Any] = [
        {"header": {"event": "task-started"}, "payload": {"output": {"type": "task-started"}}},
        {"header": {"event": "result-generated"}, "payload": {"output": {"type": "weird-future-event"}}},
        b"\x00\x01",
        {"header": {"event": "task-finished"}, "payload": {"output": {"type": "task-finished"}}},
    ]
    _patch_websockets_connect(monkeypatch, script)

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    audio, _words = await adapter.synthesize(cfg=_make_cfg(), input_=_make_request(), timeout_s=5.0)
    assert audio == b"\x00\x01"


# --------------------------------------------------------------------------- #
# Paraformer-v2 ASR fallback                                                  #
# --------------------------------------------------------------------------- #


class _FakeHttpxResponse:
    def __init__(self, status: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """超精简 httpx.AsyncClient mock，按 URL 关键字分支。"""

    def __init__(self, **_: Any) -> None:
        self.posts: list[tuple[str, dict[str, Any] | None]] = []
        self.gets: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> _FakeHttpxResponse:  # noqa: A002
        self.posts.append((url, json))
        # paraformer 任务提交
        if "asr/transcription" in url:
            return _FakeHttpxResponse(200, {"output": {"task_id": "asr-task-001"}})
        return _FakeHttpxResponse(404)

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> _FakeHttpxResponse:
        self.gets.append(url)
        if "/api/v1/tasks/" in url:
            return _FakeHttpxResponse(
                200,
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [{"transcription_url": "https://transcript.example.com/r.json"}],
                    },
                },
            )
        if "transcript.example.com" in url:
            return _FakeHttpxResponse(
                200,
                {
                    "transcripts": [
                        {
                            "sentences": [
                                {
                                    "words": [
                                        {"text": "你", "begin_time": 0, "end_time": 220},
                                        {"text": "好", "begin_time": 220, "end_time": 460},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            )
        return _FakeHttpxResponse(404)


@pytest.mark.asyncio
async def test_paraformer_submit_body_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paraformer 提交体必须含 model=paraformer-v2、file_urls、timestamp_alignment_enabled=true。"""
    import httpx  # noqa: WPS433

    fake_client_holder: dict[str, _FakeAsyncClient] = {}

    def _factory(**kw: Any) -> _FakeAsyncClient:
        c = _FakeAsyncClient(**kw)
        fake_client_holder["c"] = c
        return c

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    # 让 asyncio.sleep 不真等待
    monkeypatch.setattr(dashscope_tts.asyncio, "sleep", _async_noop)

    adapter = dashscope_tts.DashScopeTtsApiAdapter()
    words = await adapter.estimate_audio_via_asr(
        cfg=_make_cfg(),
        audio_url="https://oss.example.com/clip.mp3",
        timeout_s=10.0,
    )
    client = fake_client_holder["c"]
    submit_url, submit_body = client.posts[0]
    assert submit_url.endswith("/api/v1/services/audio/asr/transcription")
    assert submit_url.startswith("https://dashscope.aliyuncs.com")
    assert submit_body is not None
    assert submit_body["model"] == "paraformer-v2"
    assert submit_body["input"]["file_urls"] == ["https://oss.example.com/clip.mp3"]
    assert submit_body["parameters"]["timestamp_alignment_enabled"] is True
    # poll URL 模式
    assert any("/api/v1/tasks/asr-task-001" in u for u in client.gets)
    # 解析结果
    assert len(words) == 2
    assert words[0].text == "你"
    assert words[0].begin_ms == 0
    assert words[0].end_ms == 220
    assert words[1].text == "好"
    assert words[1].end_ms == 460


async def _async_noop(*_: Any, **__: Any) -> None:
    return None
