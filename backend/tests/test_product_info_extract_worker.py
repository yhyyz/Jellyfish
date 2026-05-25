"""``product_info_extract_worker`` 功能性测试（W5-T1）。

测试目标：

1. ``run_product_info_extract_task`` 在合法 ``run_args`` 下：
   - 调用 :class:`ProductExtractorAgent.a_extract_product`；
   - 把结果通过 ``model_dump(mode="json")`` 写入任务存储；
   - 把任务状态推进到 ``succeeded``，进度推进到 100。
2. 空 ``raw_text`` 立刻抛出 ``ValueError``，避免向 LLM 发出请求。
3. ``target_fields`` 列表透传到 Agent，列表元素保持顺序与内容一致。
4. ``target_fields`` 为 ``None`` 时透传 ``None``，而不是空列表。
5. ``task_executor_registry`` 正确解析 ``product_info_extract`` task_kind
   并返回 :class:`AbstractAsyncDelegatingExecutor`。
6. 工厂构造的执行器 ``timeout_seconds`` 必须为 plan 约定的 ``300.0s``。
7. 写入任务存储的 dict 必须能够通过
   :meth:`ProductExtractionResult.model_validate` 反向校验，证明
   ``model_dump(mode="json")`` 序列化路径不丢字段。

测试不依赖任何真实数据库或 LLM：

- LLM 工厂 ``build_default_text_llm_sync`` 用 ``MagicMock`` 替换；
- ``ProductExtractorAgent.a_extract_product`` 用 ``AsyncMock`` 替换；
- ``async_session_maker`` 用最小可用的 fake session context manager 替换，
  fake session 内部维护一个 in-memory ``GenerationTask`` 行，
  以便 ``SqlAlchemyTaskStore`` 的 ``set_status`` / ``set_result`` 等
  方法能访问到。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.contracts.story import ProductExtractionResult
from app.core.task_manager.types import TaskStatus
from app.models.task import GenerationTask
from app.services.commerce import product_info_extract_worker as worker_mod
from app.services.commerce.product_info_extract_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_product_info_extract_executor,
    run_product_info_extract_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures：fake session / fake store / 固定的 ProductExtractionResult
# ---------------------------------------------------------------------------


_VALID_RESULT = ProductExtractionResult(
    name="Quasar Phone Pro",
    brand="Quasar",
    category="electronics",
    description="旗舰智能手机，主打影像与续航。",
    price_anchor=4999.0,
    sku="QPP-512-BLK",
    selling_points=["120Hz 屏幕", "5000mAh 电池"],
    pain_points_solved=["续航焦虑", "影像不清"],
    target_audience={"age_range": "25-45", "gender": "all"},
    catchphrases=["拍出大片"],
    competitor_names=["Galaxy S24"],
    health_disclaimer_required=False,
)


class _FakeRow:
    """模拟 ``GenerationTask`` 行：仅持有 ``SqlAlchemyTaskStore`` 需要的字段。"""

    # pylint: disable=too-few-public-methods

    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.status = TaskStatus.pending.value
        self.progress = 0
        self.result = None
        self.error = None
        self.cancel_requested = False
        # ``SqlAlchemyTaskStore._update_columns`` 会读 / 写 started_at /
        # finished_at 来记录运行窗口；fake 行必须显式声明这两列，否则
        # ``getattr`` 会抛 ``AttributeError``。
        self.started_at = None
        self.finished_at = None


class _FakeAsyncSession:
    """提供 ``run_sync`` / ``commit`` / ``rollback`` 的最小 async session 替身。

    存在原因：
        worker 通过 ``async_session_maker()`` 进入业务事务并依赖
        ``SqlAlchemyTaskStore`` 维护任务状态。如果让测试启动真实异步
        SQLAlchemy 引擎，会牵动整张表迁移，对单测来说过重。
        本 fake 直接持有一个 in-memory 行字典，
        让 ``SqlAlchemyTaskStore`` 的 ``get`` 能命中并写入字段，
        其它操作（``commit``/``rollback``/``run_sync``）做幂等空实现。
    """

    def __init__(self, rows: dict[str, _FakeRow]) -> None:
        self._rows = rows
        self.committed = 0
        self.rolled_back = 0

    async def get(self, model: type, key: Any) -> Any:
        if model is GenerationTask:
            return self._rows.get(str(key))
        return None

    async def run_sync(self, fn: Any) -> Any:
        # worker 用 ``run_sync`` 调用同步 LLM 工厂；测试里直接同步执行。
        return fn(MagicMock(name="sync_session"))

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def flush(self) -> None:  # pragma: no cover - 仅为兼容接口
        return None


def _install_fake_session_maker(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeRow]:
    """把 ``worker_mod.async_session_maker`` 替换为 in-memory fake。"""
    rows: dict[str, _FakeRow] = {}

    @asynccontextmanager
    async def _maker():
        session = _FakeAsyncSession(rows)
        yield session

    monkeypatch.setattr(worker_mod, "async_session_maker", _maker)
    return rows


def _install_fake_llm_factory(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """把同步 LLM 工厂替换为返回 ``MagicMock`` 的 stub。"""
    fake_llm = MagicMock(name="fake_llm")
    factory = MagicMock(name="build_default_text_llm_sync", return_value=fake_llm)
    monkeypatch.setattr(worker_mod, "build_default_text_llm_sync", factory)
    return fake_llm


def _install_fake_agent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_value: ProductExtractionResult | None = None,
) -> AsyncMock:
    """把 ``ProductExtractorAgent`` 替换为类工厂返回的 mock 实例。"""
    extract_mock = AsyncMock(return_value=return_value or _VALID_RESULT)
    agent_instance = MagicMock(name="ProductExtractorAgent_instance")
    agent_instance.a_extract_product = extract_mock
    agent_cls = MagicMock(name="ProductExtractorAgent_cls", return_value=agent_instance)
    monkeypatch.setattr(worker_mod, "ProductExtractorAgent", agent_cls)
    return extract_mock


def _install_no_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cancel_if_requested_async`` 永远返回 False，避免触发取消短路。"""

    async def _never_cancel(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never_cancel)


# ---------------------------------------------------------------------------
# 注册元数据测试
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """``task_executor_registry.resolve("product_info_extract")`` 应命中本 worker。"""
    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_300s() -> None:
    """``timeout_seconds`` 必须保持在 plan 约定的 300.0s。"""
    executor = build_product_info_extract_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 300.0
    assert executor.task_kind == TASK_KIND


# ---------------------------------------------------------------------------
# 输入校验测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_raises_on_empty_raw_text() -> None:
    """``raw_text`` 空字符串应立刻抛 ``ValueError``，不应进入 session。"""
    with pytest.raises(ValueError, match="raw_text"):
        await run_product_info_extract_task("task-1", {"raw_text": "   "})


@pytest.mark.asyncio
async def test_runner_raises_on_missing_raw_text() -> None:
    """``raw_text`` 完全缺失也应触发同样的早抛。"""
    with pytest.raises(ValueError, match="raw_text"):
        await run_product_info_extract_task("task-1", {})


# ---------------------------------------------------------------------------
# Happy-path 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_extracts_product_with_valid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法输入下：调用 Agent、写 result、把状态推进到 succeeded。"""
    rows = _install_fake_session_maker(monkeypatch)
    rows["task-ok"] = _FakeRow("task-ok")
    _install_no_cancel(monkeypatch)
    _install_fake_llm_factory(monkeypatch)
    extract_mock = _install_fake_agent(monkeypatch)

    await run_product_info_extract_task(
        "task-ok",
        {
            "raw_text": "iPhone 15 Pro 商品页文本……",
            "target_fields": ["name", "selling_points"],
        },
    )

    extract_mock.assert_awaited_once()
    row = rows["task-ok"]
    assert row.status == TaskStatus.succeeded.value
    assert row.progress == 100
    assert row.result is not None
    assert row.result["name"] == "Quasar Phone Pro"
    assert row.error in (None, "")


@pytest.mark.asyncio
async def test_runner_passes_target_fields_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """``target_fields`` 列表应原样透传给 Agent.a_extract_product。"""
    rows = _install_fake_session_maker(monkeypatch)
    rows["task-tf"] = _FakeRow("task-tf")
    _install_no_cancel(monkeypatch)
    _install_fake_llm_factory(monkeypatch)
    extract_mock = _install_fake_agent(monkeypatch)

    target_fields = ["name", "brand", "selling_points"]
    await run_product_info_extract_task(
        "task-tf",
        {"raw_text": "raw", "target_fields": target_fields},
    )

    extract_mock.assert_awaited_once()
    kwargs = extract_mock.await_args.kwargs
    assert kwargs["raw_text"] == "raw"
    assert kwargs["target_fields"] == target_fields


@pytest.mark.asyncio
async def test_runner_handles_none_target_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """``target_fields`` 缺失/空列表 → Agent 收到 ``None``，不是 ``[]``。"""
    rows = _install_fake_session_maker(monkeypatch)
    rows["task-none"] = _FakeRow("task-none")
    _install_no_cancel(monkeypatch)
    _install_fake_llm_factory(monkeypatch)
    extract_mock = _install_fake_agent(monkeypatch)

    await run_product_info_extract_task(
        "task-none",
        {"raw_text": "raw", "target_fields": []},
    )
    extract_mock.assert_awaited_once()
    assert extract_mock.await_args.kwargs["target_fields"] is None

    # 同样验证：缺省键也走 None 分支。
    extract_mock.reset_mock()
    await run_product_info_extract_task("task-none", {"raw_text": "raw"})
    extract_mock.assert_awaited_once()
    assert extract_mock.await_args.kwargs["target_fields"] is None


@pytest.mark.asyncio
async def test_runner_serializes_result_via_model_dump_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``set_result`` 写入的 dict 必须能反向 ``model_validate``。"""
    rows = _install_fake_session_maker(monkeypatch)
    rows["task-roundtrip"] = _FakeRow("task-roundtrip")
    _install_no_cancel(monkeypatch)
    _install_fake_llm_factory(monkeypatch)
    _install_fake_agent(monkeypatch)

    await run_product_info_extract_task("task-roundtrip", {"raw_text": "raw"})

    payload = rows["task-roundtrip"].result
    assert isinstance(payload, dict)
    # 反序列化必须无损，证明 ``mode="json"`` 没丢字段。
    roundtrip = ProductExtractionResult.model_validate(payload)
    assert roundtrip.name == _VALID_RESULT.name
    assert roundtrip.selling_points == _VALID_RESULT.selling_points
    assert roundtrip.target_audience == _VALID_RESULT.target_audience
    assert roundtrip.health_disclaimer_required is False


# ---------------------------------------------------------------------------
# 失败路径测试：Agent 抛错 → worker 写 failed 并 re-raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent 抛错时：原会话 rollback、单独会话写 failed、再向上抛。"""
    rows = _install_fake_session_maker(monkeypatch)
    rows["task-fail"] = _FakeRow("task-fail")
    _install_no_cancel(monkeypatch)
    _install_fake_llm_factory(monkeypatch)
    extract_mock = _install_fake_agent(monkeypatch)
    extract_mock.side_effect = RuntimeError("upstream LLM 503")

    with pytest.raises(RuntimeError, match="upstream LLM 503"):
        await run_product_info_extract_task("task-fail", {"raw_text": "raw"})

    row = rows["task-fail"]
    assert row.status == TaskStatus.failed.value
    assert row.error == "upstream LLM 503"
