"""W5-T3: ``compliance_check`` worker 执行器与持久化回归测试。

测试策略：
    - 使用真实 SQLite (in-memory + file) + ``Base.metadata.create_all`` 建表，
      让 ``compliance_findings`` / ``story_variants`` 走完整 ORM 路径；
    - 复用 W4-T3 的 ``_MockChatModel`` 思路：把 ``langchain_openai.ChatOpenAI``
      在 worker 路径上 monkeypatch 成一个返回固定 :class:`ComplianceReport`
      JSON 的 ``BaseChatModel``，避免触网；
    - **不**替换 :class:`ComplianceRuleEngine`：本任务的集成价值就是规则引擎
      的真实命中（如缺 "演绎" → ``cn_yanyi_label`` blocker），mock 掉就失去
      意义；
    - 验证项分四类：DB 持久化、output payload、入参校验、注册表对接。
"""

# pylint: disable=protected-access,too-few-public-methods,redefined-outer-name

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import DeliveryMode
from app.models.compliance import ComplianceFinding
from app.models.story_formula import StoryFormula, StoryVariant
from app.models.studio import Chapter, Project
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.types import (
    ComplianceSeverity,
    ProjectStyle,
    PromptCategory,
)
from app.services.commerce import compliance_check_worker
from app.services.commerce.compliance_check_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    run_compliance_check_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# 共用 LLM mock & ComplianceReport 构造工具
# ---------------------------------------------------------------------------


class _MockChatModel(BaseChatModel):
    """复用 W4-T3 风格的 LangChain ``BaseChatModel``：恒定返回单一字符串。

    我们在 worker 路径里通过 monkeypatch ``langchain_openai.ChatOpenAI``
    把这个类塞进去，于是 ``build_default_text_llm`` 拿到的就是这个 mock。
    """

    response: str = ""

    def __init__(self, response: str = "", **_kwargs: Any) -> None:
        super().__init__()
        # ``BaseChatModel`` 走 pydantic，需要绕过 frozen 风格地塞字段。
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议要求
        return "mock-compliance-worker-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,  # pylint: disable=unused-argument
        stop: Any = None,  # pylint: disable=unused-argument
        run_manager: Any = None,  # pylint: disable=unused-argument
        **_kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )


def _empty_llm_report_json(
    *,
    region: str = "cn_mainland",
    product_category: str = "other",
) -> str:
    """LLM 端返回"未发现风险"的标准 ComplianceReport JSON。"""

    return json.dumps(
        {
            "variant_id": None,
            "region": region,
            "product_category": product_category,
            "findings": [],
            "score": 100,
            "summary": "未发现合规风险。",
        }
    )


def _llm_report_json_with_findings(findings: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "variant_id": None,
            "region": "cn_mainland",
            "product_category": "other",
            "findings": findings,
            "score": 50,
            "summary": "存在风险",
        }
    )


# ---------------------------------------------------------------------------
# 共用 fixture：内存 SQLite + 默认 Provider/Model + StoryVariant
# ---------------------------------------------------------------------------


async def _seed_provider_and_model(db: AsyncSession) -> None:
    """补齐 ``build_default_text_llm`` 所需的 Provider + Model + ModelSettings。

    ``build_default_text_llm`` 会查 ``ModelSettings(id=1).default_text_model_id``，
    再据此取 ``Model`` / ``Provider``。本 fixture 用最小可行配置满足这条链路；
    ``Provider.api_key`` 必须非空，否则 service 会直接 503。
    """

    # 局部 import 避免顶层污染（仅 fixture 用得到）。
    from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider

    db.add(
        Provider(
            id="prov-1",
            name="MockProvider",
            base_url="http://example.invalid",
            api_key="sk-test",
        )
    )
    db.add(
        Model(
            id="model-1",
            provider_id="prov-1",
            name="mock-text-model",
            category=ModelCategoryKey.text,
            params={},
        )
    )
    db.add(
        ModelSettings(
            id=1,
            default_text_model_id="model-1",
            default_image_model_id=None,
            default_video_model_id=None,
        )
    )
    await db.flush()


async def _seed_variant(
    db: AsyncSession,
    *,
    variant_id: str = "var-test",
    script_full_text: str = "",
) -> None:
    """种入 Project / Chapter / PromptTemplate / StoryFormula / StoryVariant。

    最小可行字段集：足以让 :class:`StoryVariant` FK 链路全部解析成功。
    """

    db.add(
        Project(
            id="proj-1",
            name="测试项目",
            style=ProjectStyle.real_people_city,
        )
    )
    db.add(
        Chapter(
            id="chap-1",
            project_id="proj-1",
            index=1,
            title="第 1 章",
        )
    )
    db.add(
        PromptTemplate(
            id="tpl-1",
            category=PromptCategory.video_prompt,
            name="占位模板",
            content="...",
        )
    )
    db.add(
        StoryFormula(
            id="formula-1",
            name="测试公式",
            prompt_template_id="tpl-1",
        )
    )
    db.add(
        StoryVariant(
            id=variant_id,
            project_id="proj-1",
            chapter_id="chap-1",
            formula_id="formula-1",
            script_full_text=script_full_text,
        )
    )
    await db.flush()


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造一个 file-backed SQLite 引擎并返回 async_sessionmaker。

    用 file-backed 而非 ``:memory:``，是因为 worker 内部多次开
    ``async_session_maker()``，必须看到同一个数据库；多 connection 的
    ``:memory:`` 会各自得到独立内存库，破坏断言。
    """

    db_path = tmp_path / "compliance-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


def _patch_session_maker(monkeypatch: pytest.MonkeyPatch, session_local: Any) -> None:
    """让 worker 内部的 ``async_session_maker`` 指向测试 session_local。

    必须 patch 两处：
        1. worker 模块本身（顶层导入）；
        2. ``app.core.db`` 全局（防御性，避免间接路径绕过）。
    """

    monkeypatch.setattr(
        "app.services.commerce.compliance_check_worker.async_session_maker",
        session_local,
    )


def _patch_chat_openai(monkeypatch: pytest.MonkeyPatch, llm: BaseChatModel) -> None:
    """把 ``langchain_openai.ChatOpenAI`` 替换成 ``lambda **_: llm``。"""

    monkeypatch.setattr(
        "langchain_openai.ChatOpenAI",
        lambda **_kwargs: llm,
    )


async def _create_task(
    session_local: Any,
    *,
    run_args: dict[str, Any],
) -> str:
    """在测试 DB 里建一条 ``GenerationTask`` 并返回 task_id。"""

    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": TASK_KIND, "run_args": run_args},
            mode=DeliveryMode.async_polling,
            task_kind=TASK_KIND,
        )
        await db.commit()
        return task.id


# ---------------------------------------------------------------------------
# 1. 持久化 — finding 行 + variant.compliance_score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_persists_compliance_findings_to_db(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺 "演绎" 的脚本 → cn_yanyi_label 写入 compliance_findings 表。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-1",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天给大家推荐一款产品。",
        },
    )

    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-1",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天给大家推荐一款产品。",
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(ComplianceFinding.variant_id == "var-1")
            )
        ).scalars().all()

    assert rows, "expected at least one ComplianceFinding row to be persisted"
    rule_ids = {row.rule_id for row in rows}
    assert "cn_yanyi_label" in rule_ids
    yanyi = next(r for r in rows if r.rule_id == "cn_yanyi_label")
    assert yanyi.severity == ComplianceSeverity.blocker
    assert yanyi.is_resolved is False
    assert yanyi.detected_at is not None


@pytest.mark.asyncio
async def test_runner_updates_variant_compliance_score(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """运行后 ``StoryVariant.compliance_score`` 反映 report.score。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-2")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-2",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",  # 缺 演绎 → 1 个 blocker → score=75
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-2",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",
        },
    )

    async with session_local() as db:
        variant = await db.get(StoryVariant, "var-2")
        assert variant is not None
        # 1 blocker (cn_yanyi_label) → 100 - 25 = 75
        assert variant.compliance_score == 75


@pytest.mark.asyncio
async def test_runner_returns_finding_counts_in_output(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """output payload 含 findings_count / blocker_count / warning_count / info_count。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-counts")
        await db.commit()

    # LLM 再补一条 warning，配合规则端 cn_yanyi_label blocker，验证多等级计数
    llm_findings = [
        {
            "rule_id": "llm_extra",
            "rule_kind": "banned_phrase",
            "severity": "warning",
            "description": "warning sample",
            "location": "Shot 1",
            "suggested_fix": "...",
        }
    ]
    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(_llm_report_json_with_findings(llm_findings)),
    )

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-counts",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-counts",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",
        },
    )

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        assert task is not None
        result = task.result
        assert result is not None
        assert result["variant_id"] == "var-counts"
        assert result["findings_count"] == 2
        assert result["blocker_count"] == 1
        assert result["warning_count"] == 1
        assert result["info_count"] == 0
        assert result["score"] == 100 - 25 - 5  # 1 blocker + 1 warning


@pytest.mark.asyncio
async def test_runner_returns_summary_in_output(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """output payload 直接透传 ComplianceReport.summary。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-summary")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    # clean 脚本：含演绎、含健康免责、不触发任何规则。
    clean_script = "本视频为剧情演绎，产品功效因人而异，非医疗器械。今天分享一款好用的产品。"

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-summary",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": clean_script,
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-summary",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": clean_script,
        },
    )

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == GenerationTaskStatus.succeeded
        result = task.result or {}
        assert result.get("summary") == "未发现合规风险。"
        assert result.get("findings_count") == 0


# ---------------------------------------------------------------------------
# 2. 入参校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_raises_on_missing_variant_id(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``variant_id`` 缺失 → task 标记 failed，error 含提示。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-x")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "x",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "x",
        },
    )

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == GenerationTaskStatus.failed
        assert "variant_id" in (task.error or "")


@pytest.mark.asyncio
async def test_runner_raises_on_invalid_region(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 ComplianceRegion 取值 → task failed。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-bad-region")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-bad-region",
            "region": "mars",
            "product_category": "other",
            "script_text": "演绎短片",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-bad-region",
            "region": "mars",
            "product_category": "other",
            "script_text": "演绎短片",
        },
    )

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == GenerationTaskStatus.failed
        assert "region" in (task.error or "")


@pytest.mark.asyncio
async def test_runner_raises_on_invalid_product_category(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 ProductCategory 取值 → task failed。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-bad-cat")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-bad-cat",
            "region": "cn_mainland",
            "product_category": "spaceship",
            "script_text": "演绎短片",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-bad-cat",
            "region": "cn_mainland",
            "product_category": "spaceship",
            "script_text": "演绎短片",
        },
    )

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        assert task is not None
        assert task.status == GenerationTaskStatus.failed
        assert "product_category" in (task.error or "")


# ---------------------------------------------------------------------------
# 3. script_text 解析路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_uses_provided_script_text_directly(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式传 ``script_text`` 时不读 StoryVariant.script_full_text。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        # variant 自带 "演绎" 应该满足 yanyi 规则；如果 worker 错读了
        # variant 文本，反而不会触发任何规则；显式传"今天推荐一款产品"
        # （无演绎）则一定会触发 yanyi blocker。
        await _seed_variant(
            db,
            variant_id="var-explicit",
            script_full_text="本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        )
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-explicit",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-explicit",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天推荐一款产品。",
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(
                    ComplianceFinding.variant_id == "var-explicit"
                )
            )
        ).scalars().all()
        rule_ids = {row.rule_id for row in rows}
    # 显式 script_text（无演绎）触发了 yanyi → 证明 worker 用了显式文本。
    assert "cn_yanyi_label" in rule_ids


@pytest.mark.asyncio
async def test_runner_falls_back_to_variant_script_when_text_omitted(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``script_text=None`` → 回退使用 ``StoryVariant.script_full_text``。"""

    session_local = session_factory
    # Variant 自带"演绎"满足 yanyi；不应再产出 yanyi finding。
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(
            db,
            variant_id="var-fallback",
            script_full_text="本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        )
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-fallback",
            "region": "cn_mainland",
            "product_category": "other",
            # 注意：没有 script_text 字段
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-fallback",
            "region": "cn_mainland",
            "product_category": "other",
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(
                    ComplianceFinding.variant_id == "var-fallback"
                )
            )
        ).scalars().all()
        rule_ids = {row.rule_id for row in rows}
    assert "cn_yanyi_label" not in rule_ids


# ---------------------------------------------------------------------------
# 4. brand_aliases 透传
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_passes_brand_aliases_to_agent(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_args.brand_aliases 透传到 ComplianceCheckerAgent.a_check 的 kwargs。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(
            db,
            variant_id="var-brand",
            script_full_text="演绎短片：分享我家的护肤品。",
        )
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    captured: dict[str, Any] = {}

    real_a_check = (
        compliance_check_worker.ComplianceCheckerAgent.a_check  # type: ignore[attr-defined]
    )

    async def _spy_a_check(self: Any, **kwargs: Any):  # noqa: ANN001
        captured.update(kwargs)
        return await real_a_check(self, **kwargs)  # pylint: disable=missing-kwoa

    monkeypatch.setattr(
        "app.services.commerce.compliance_check_worker.ComplianceCheckerAgent.a_check",
        _spy_a_check,
    )

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-brand",
            "region": "cn_mainland",
            "product_category": "beauty",
            "script_text": "演绎短片：分享我家的护肤品。",
            "brand_aliases": ["Acme", "ACME家"],
            "script_duration_sec": 90,
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-brand",
            "region": "cn_mainland",
            "product_category": "beauty",
            "script_text": "演绎短片：分享我家的护肤品。",
            "brand_aliases": ["Acme", "ACME家"],
            "script_duration_sec": 90,
        },
    )

    assert captured.get("brand_aliases") == ("Acme", "ACME家")
    assert captured.get("script_duration_sec") == 90


# ---------------------------------------------------------------------------
# 5. 不同输入下的检查产出
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_creates_zero_findings_for_clean_script(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """clean 脚本 → 0 findings + score=100 + summary "未发现合规风险。"。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-clean")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    clean_script = "本视频为剧情演绎，产品功效因人而异，非医疗器械。今天分享一款好用的产品。"
    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-clean",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": clean_script,
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-clean",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": clean_script,
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(ComplianceFinding.variant_id == "var-clean")
            )
        ).scalars().all()
        variant = await db.get(StoryVariant, "var-clean")
        task = await db.get(GenerationTask, task_id)

    assert rows == []
    assert variant is not None
    assert variant.compliance_score == 100
    assert task is not None and task.status == GenerationTaskStatus.succeeded
    assert (task.result or {}).get("summary") == "未发现合规风险。"


@pytest.mark.asyncio
async def test_runner_creates_blocker_finding_for_missing_yanyi(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """脚本缺 演绎/虚构 → cn_yanyi_label blocker 写入 DB。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-yanyi")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-yanyi",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天给大家推荐一款产品。",  # 无 演绎 / 虚构
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-yanyi",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "今天给大家推荐一款产品。",
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(ComplianceFinding.variant_id == "var-yanyi")
            )
        ).scalars().all()

    yanyi = next((r for r in rows if r.rule_id == "cn_yanyi_label"), None)
    assert yanyi is not None
    assert yanyi.severity == ComplianceSeverity.blocker
    assert yanyi.rule_kind == "required_label"


# ---------------------------------------------------------------------------
# 6. 注册表 / 配置常量
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """task_executor_registry 解析 ``compliance_check`` → AbstractAsyncDelegatingExecutor。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_180s() -> None:
    """注册时使用 ``DEFAULT_TIMEOUT_SEC`` (180s) 作为默认超时。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    # AbstractAsyncDelegatingExecutor 在 __init__ 把 timeout_seconds 写到实例上
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 180.0


# ---------------------------------------------------------------------------
# 7. severity Literal → ComplianceSeverity 枚举映射
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_severity_string_to_enum_conversion(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 返回的 ``severity="info"|"warning"|"blocker"`` 全部正确落到 ORM 枚举。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(
            db,
            variant_id="var-sev",
            script_full_text="本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        )
        await db.commit()

    llm_findings = [
        {
            "rule_id": "llm_info_1",
            "rule_kind": "banned_phrase",
            "severity": "info",
            "description": "info sample",
            "location": "Shot 1",
            "suggested_fix": "...",
        },
        {
            "rule_id": "llm_warn_1",
            "rule_kind": "banned_phrase",
            "severity": "warning",
            "description": "warning sample",
            "location": "Shot 2",
            "suggested_fix": "...",
        },
        {
            "rule_id": "llm_block_1",
            "rule_kind": "banned_phrase",
            "severity": "blocker",
            "description": "blocker sample",
            "location": "Shot 3",
            "suggested_fix": "...",
        },
    ]
    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(_llm_report_json_with_findings(llm_findings)),
    )

    task_id = await _create_task(
        session_local,
        run_args={
            "variant_id": "var-sev",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        },
    )
    await run_compliance_check_task(
        task_id,
        {
            "variant_id": "var-sev",
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": "本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        },
    )

    async with session_local() as db:
        rows = (
            await db.execute(
                select(ComplianceFinding).where(ComplianceFinding.variant_id == "var-sev")
            )
        ).scalars().all()

    by_rule = {row.rule_id: row for row in rows}
    assert by_rule["llm_info_1"].severity == ComplianceSeverity.info
    assert by_rule["llm_warn_1"].severity == ComplianceSeverity.warning
    assert by_rule["llm_block_1"].severity == ComplianceSeverity.blocker


# ---------------------------------------------------------------------------
# 8. 兜底：worker import 不会破坏现有注册项
# ---------------------------------------------------------------------------


def test_existing_registrations_still_resolve() -> None:
    """新增 ``compliance_check`` 不影响既有 task_kind 解析。"""

    for known in ("script_divide", "video_generation", "image_generation"):
        executor = task_executor_registry.resolve(known)
        assert executor is not None


# ---------------------------------------------------------------------------
# 9. 幂等：同一 task 仅 set_result 一次（避免 double-write）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_set_result_called_once_per_task(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功路径下 ``store.set_result`` 仅被调用一次（防 double-write 回归）。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(
            db,
            variant_id="var-idem",
            script_full_text="本视频为剧情演绎，产品功效因人而异，非医疗器械。",
        )
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_empty_llm_report_json()))

    call_count = {"set_result": 0}
    real_set_result = SqlAlchemyTaskStore.set_result

    async def _counted_set_result(self: Any, task_id: str, result: Any) -> None:
        call_count["set_result"] += 1
        await real_set_result(self, task_id, result)

    with patch.object(SqlAlchemyTaskStore, "set_result", _counted_set_result):
        task_id = await _create_task(
            session_local,
            run_args={
                "variant_id": "var-idem",
                "region": "cn_mainland",
                "product_category": "other",
            },
        )
        await run_compliance_check_task(
            task_id,
            {
                "variant_id": "var-idem",
                "region": "cn_mainland",
                "product_category": "other",
            },
        )

    assert call_count["set_result"] == 1
