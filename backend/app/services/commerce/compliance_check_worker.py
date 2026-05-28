"""W5-T3: ``compliance_check`` 任务的 worker 执行器。

为什么存在：
    ``ComplianceCheckerAgent``（W4-T3）只负责"对一段文本做合规检查、产出
    :class:`ComplianceReport`"，本身不知道 DB、不知道 Celery、也不写
    :class:`ComplianceFinding` 表。Worker 这一层补齐"被动接调度 / 写
    持久化结果"两件事：

    1. 读取 ``GenerationTask.payload.run_args`` 的入参（variant_id /
       region / product_category / script_text / 时长 / 品牌词）；
    2. 校验入参的合法性（含 enum 值校验），对 ``script_text`` 缺省时
       回退到 :class:`StoryVariant.script_full_text`；
    3. 构造 ``ComplianceCheckerAgent`` 并 ``await a_check(...)``；
    4. 把每条 finding 写入 ``compliance_findings`` 表（CASCADE 跟
       variant 走），把 ``variant.compliance_score`` 同步刷新；
    5. 返回一个轻量的统计字典（变体 ID + 分数 + 各等级计数 + 摘要），
       由 worker 统一序列化进 ``GenerationTask.result``，供前端做
       任务中心展示与回跳。

    本模块**不**实现取消/状态/超时这些通用编排逻辑——这些由
    :class:`AbstractAsyncDelegatingExecutor` 在
    ``app.services.worker.task_registry`` 中统一封装，本模块只把
    ``run_compliance_check_task`` 暴露成一个纯净的 async runner。

边界：
    - 不修改 ``ComplianceCheckerAgent`` / ``ComplianceRuleEngine`` /
      ``builtin_rules``（W3-T3 / W4-T3 owns）。
    - 不修改 :class:`ComplianceFinding` 模型（W2-T3 owns）。
    - 不暴露任何 HTTP 端点（W6 owns）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents.commerce.compliance_checker_agent import ComplianceCheckerAgent
from app.config import settings
from app.core.contracts.story import ComplianceReport
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.integrations.notifications.email import SmtpConfig
from app.models.compliance import ComplianceFinding
from app.models.story_formula import StoryVariant
from app.models.types import ComplianceRegion, ComplianceSeverity, ProductCategory
from app.services.llm.resolver import build_default_text_llm
from app.services.notifications.compliance_dispatcher import (
    BlockerFindingPayload,
    dispatch_blocker_findings,
)
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共常量：task_kind / 默认超时
# ---------------------------------------------------------------------------

#: 该执行器在任务系统中的 ``task_kind`` 主键。
TASK_KIND: str = "compliance_check"

#: 默认硬超时（秒）。规则扫描是 O(N+L) 线性、LLM 单次调用为主，
#: P1 阶段 180s 足以覆盖正常脚本（≤ 60s 时长，≤ 1000 字脚本）。
#: 由 :class:`AbstractAsyncDelegatingExecutor` 在外层用 ``asyncio.wait_for``
#: 强制兜底，避免单次运行长时间占着 Celery slot。
DEFAULT_TIMEOUT_SEC: float = 180.0


# ---------------------------------------------------------------------------
# 入参校验（不依赖任何外部框架，便于单测）
# ---------------------------------------------------------------------------


def _coerce_region(raw: Any) -> ComplianceRegion:
    """把任意入参值映射为 :class:`ComplianceRegion`。

    Args:
        raw: 调度层传进来的原始值，理论上是 ``ComplianceRegion`` 的
            字符串值（如 ``"cn_mainland"``），但 Celery 序列化路径会丢
            类型信息，所以这里统一从字符串构造。

    Returns:
        合法的 :class:`ComplianceRegion` 枚举。

    Raises:
        ValueError: 入参缺失或不是 ``ComplianceRegion`` 已声明的取值。
    """

    if isinstance(raw, ComplianceRegion):
        return raw
    if not isinstance(raw, str) or not raw:
        raise ValueError("region is required and must be a ComplianceRegion value")
    try:
        return ComplianceRegion(raw)
    except ValueError as exc:
        valid = ", ".join(member.value for member in ComplianceRegion)
        raise ValueError(
            f"invalid region={raw!r}; expected one of: {valid}"
        ) from exc


def _coerce_product_category(raw: Any) -> ProductCategory:
    """把任意入参值映射为 :class:`ProductCategory`。

    Args:
        raw: 调度层传进来的原始值，约定为 ``ProductCategory`` 的字符串值。

    Returns:
        合法的 :class:`ProductCategory` 枚举。

    Raises:
        ValueError: 入参缺失或不是 ``ProductCategory`` 已声明的取值。
    """

    if isinstance(raw, ProductCategory):
        return raw
    if not isinstance(raw, str) or not raw:
        raise ValueError(
            "product_category is required and must be a ProductCategory value"
        )
    try:
        return ProductCategory(raw)
    except ValueError as exc:
        valid = ", ".join(member.value for member in ProductCategory)
        raise ValueError(
            f"invalid product_category={raw!r}; expected one of: {valid}"
        ) from exc


def _coerce_brand_aliases(raw: Any) -> tuple[str, ...]:
    """把入参的 ``brand_aliases`` 归一为去空的字符串元组。

    Celery 序列化默认走 JSON，所以这里只接受 list/tuple；任何 ``None``
    或非序列输入都视为"未注入"，返回空元组（与规则引擎"未注入"语义对齐）。
    """

    if not raw:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("brand_aliases must be a list or tuple of strings")
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("brand_aliases items must be strings")
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return tuple(cleaned)


def _coerce_duration_sec(raw: Any) -> int:
    """归一脚本时长（秒），缺省回退到 60。"""

    if raw is None or raw == "":
        return 60
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("script_duration_sec must be an integer") from exc
    if value <= 0:
        raise ValueError("script_duration_sec must be > 0")
    return value


# ---------------------------------------------------------------------------
# 工具函数：把 LLM 严重等级（Pydantic Literal）转为 ORM 枚举
# ---------------------------------------------------------------------------


def _severity_to_enum(severity: str) -> ComplianceSeverity:
    """把 :class:`ComplianceFinding`（Pydantic）里的字符串字面量
    映射为 ORM 枚举 :class:`ComplianceSeverity`。

    Pydantic 契约用 ``Literal["info", "warning", "blocker"]``；ORM 列定
    义为 :class:`ComplianceSeverity`，二者底层都是相同的字符串值，
    但显式做一次构造可避免后续如果两端语义漂移时静默错位。
    """

    try:
        return ComplianceSeverity(severity)
    except ValueError as exc:
        raise ValueError(
            f"unknown compliance severity from agent: {severity!r}"
        ) from exc


# ---------------------------------------------------------------------------
# 持久化：把 ComplianceReport 写入 DB
# ---------------------------------------------------------------------------


async def _persist_findings(
    session: AsyncSession,
    *,
    variant_id: str,
    report: ComplianceReport,
) -> list[ComplianceFinding]:
    """把 :class:`ComplianceReport` 全量写入 ``compliance_findings`` 并
    同步 :class:`StoryVariant.compliance_score`。

    设计要点：
        - 每次任务执行都新增 finding 行（不做去重 / upsert）。本期
          P1 暂不做"复跑刷新"：上层先支持"看到一条历史就能回追触发
          任务"，重复 finding 由前端 / W6 service 层后续按需聚合。
        - ``detected_at`` 用 :func:`datetime.now(timezone.utc)` 直接写入；
          ``ComplianceFinding.detected_at`` 列在两端 DB 上对 timezone-aware
          值都会做无损往返（SQLite 直接序列化 ISO 字符串，MySQL 走
          ``DateTime`` 默认行为）。
        - ``compliance_score`` 仅在 variant 真实存在时刷新；缺失时由
          调用方在装载阶段就抛错（``_load_variant_or_raise``）。
        - 返回新建的 ORM 实体列表，便于调用方在 commit 之后基于自增 ID
          触发后置链路（W26-T1：BLOCKER 告警 dispatcher）。

    Args:
        session: 当前 worker 的 async session。
        variant_id: ``compliance_findings.variant_id`` 外键值。
        report: 来自 :meth:`ComplianceCheckerAgent.a_check` 的检查结果。

    Returns:
        本次写入的 :class:`ComplianceFinding` ORM 实例列表（顺序与
        ``report.findings`` 一一对应）。
    """

    detected_at = datetime.now(timezone.utc)
    persisted: list[ComplianceFinding] = []
    for finding in report.findings:
        row = ComplianceFinding(
            variant_id=variant_id,
            severity=_severity_to_enum(finding.severity),
            rule_id=finding.rule_id,
            rule_kind=finding.rule_kind,
            description=finding.description,
            location=finding.location,
            suggested_fix=finding.suggested_fix,
            is_resolved=False,
            detected_at=detected_at,
        )
        session.add(row)
        persisted.append(row)

    variant = await session.get(StoryVariant, variant_id)
    if variant is not None:
        variant.compliance_score = report.score
    return persisted


def _summarize_counts(report: ComplianceReport) -> tuple[int, int, int]:
    """返回 ``(blocker_count, warning_count, info_count)`` 三段统计。"""

    blocker = sum(1 for f in report.findings if f.severity == "blocker")
    warning = sum(1 for f in report.findings if f.severity == "warning")
    info = sum(1 for f in report.findings if f.severity == "info")
    return blocker, warning, info


async def _fire_blocker_dispatch(
    *,
    variant_id: str,
    persisted_findings: list[ComplianceFinding],
) -> None:
    """把已落库的 BLOCKER finding 异步 fan-out 到通知渠道（W26-T1）。

    遵循 W19b chain dispatch 契约：调用本函数前必须已 ``commit()``。
    本函数把每条 BLOCKER finding 包成 :class:`BlockerFindingPayload`，
    交给 :func:`dispatch_blocker_findings` 并发执行；dispatcher 内部
    自行兜底所有异常，本函数永不向上抛错。

    构造 SMTP 配置走 :class:`Settings`：未配置 ``SMTP_HOST`` 时 email
    渠道会在 dispatcher 中被判失败，仅 Slack 渠道继续生效。
    """

    blockers = [f for f in persisted_findings if f.severity == ComplianceSeverity.blocker]
    if not blockers:
        return

    smtp_config: SmtpConfig | None = None
    smtp_sender: str | None = None
    if settings.smtp_host:
        smtp_config = SmtpConfig(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            start_tls=settings.smtp_start_tls,
            sender=settings.smtp_sender or settings.smtp_username,
        )
        smtp_sender = settings.smtp_sender or settings.smtp_username

    payloads = [
        BlockerFindingPayload(
            finding_id=row.id,
            severity=str(row.severity.value if hasattr(row.severity, "value") else row.severity),
            rule_id=row.rule_id,
            rule_kind=row.rule_kind,
            description=row.description,
            variant_id=variant_id,
            profile_id=None,
            location=row.location,
            suggested_fix=row.suggested_fix,
        )
        for row in blockers
    ]

    try:
        await dispatch_blocker_findings(
            payloads,
            smtp_config=smtp_config,
            smtp_sender=smtp_sender,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "blocker dispatch unexpected failure (suppressed)",
            extra={"variant_id": variant_id, "blocker_count": len(blockers)},
        )


def _build_output_payload(
    *,
    variant_id: str,
    report: ComplianceReport,
) -> dict[str, Any]:
    """把检查结果扁平化为 worker ``set_result`` 用的 dict。

    任务中心只展示通用任务信息（W5-T3 不引入业务上下文摘要），所以这
    里的 payload 故意保持精简：仅暴露调用方/前端做"成功/失败一眼看完"
    所需的字段。
    """

    blocker, warning, info = _summarize_counts(report)
    return {
        "variant_id": variant_id,
        "score": report.score,
        "findings_count": len(report.findings),
        "summary": report.summary,
        "blocker_count": blocker,
        "warning_count": warning,
        "info_count": info,
    }


# ---------------------------------------------------------------------------
# 入参装载：兼容"显式传 script_text"和"回退到 StoryVariant"两条路径
# ---------------------------------------------------------------------------


async def _resolve_script_text(
    session: AsyncSession,
    *,
    variant_id: str,
    explicit_script_text: str | None,
) -> str:
    """决定本次扫描使用的脚本文本。

    解析顺序：
        1. 调用方显式传入 ``script_text`` 时直接使用（包括传入空字符串
           的情况——视为调用方明确要求"扫描空脚本"，引擎会按规则触发
           ``required_label`` 之类的缺失项）。
        2. 否则按 ``variant_id`` 取 :class:`StoryVariant`，回退到
           ``variant.script_full_text``。

    Raises:
        ValueError: ``script_text`` 缺省且 variant 不存在。
    """

    if explicit_script_text is not None:
        return explicit_script_text
    variant = await session.get(StoryVariant, variant_id)
    if variant is None:
        raise ValueError(
            f"StoryVariant not found and script_text not provided: {variant_id}"
        )
    return variant.script_full_text or ""


# ---------------------------------------------------------------------------
# 公开 async runner —— 由 AbstractAsyncDelegatingExecutor 包一层后注册
# ---------------------------------------------------------------------------


async def run_compliance_check_task(  # pylint: disable=too-many-locals
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """``compliance_check`` 任务的 async runner。

    流程：
        1. 校验 / 归一入参（``variant_id``、``region``、
           ``product_category``、``script_duration_sec``、``brand_aliases``）；
        2. 取 LLM；构造 :class:`ComplianceCheckerAgent`；
        3. ``await agent.a_check(...)`` 得到 :class:`ComplianceReport`；
        4. 全量写入 ``compliance_findings`` + 刷新 ``variant.compliance_score``；
        5. 把扁平统计写入 ``GenerationTask.result``，状态置 ``succeeded``。

    任何阶段抛异常都会回滚当前事务，并以 ``failed`` 状态记录 ``error``，
    与既有 :func:`app.services.film.generated_video.run_video_generation_task`
    的失败收尾路径保持一致。

    Args:
        task_id: ``GenerationTask.id``。
        run_args: 任务入参字典，遵循以下契约：

            - ``variant_id`` (``str``, required)
            - ``region`` (``str``, required, ``ComplianceRegion`` 取值)
            - ``product_category`` (``str``, required, ``ProductCategory`` 取值)
            - ``script_text`` (``str | None``, optional；None 时回退到
              ``StoryVariant.script_full_text``)
            - ``script_duration_sec`` (``int``, optional, 默认 60)
            - ``brand_aliases`` (``list[str]``, optional, 默认 [])
    """

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 10)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            variant_id = str(run_args.get("variant_id") or "").strip()
            if not variant_id:
                raise ValueError("variant_id is required for compliance_check task")
            region = _coerce_region(run_args.get("region"))
            product_category = _coerce_product_category(run_args.get("product_category"))
            duration = _coerce_duration_sec(run_args.get("script_duration_sec"))
            brand_aliases = _coerce_brand_aliases(run_args.get("brand_aliases"))

            explicit_script_text = run_args.get("script_text")
            if explicit_script_text is not None and not isinstance(explicit_script_text, str):
                raise ValueError("script_text must be a string when provided")
            script_text = await _resolve_script_text(
                session,
                variant_id=variant_id,
                explicit_script_text=explicit_script_text,
            )

            llm = await build_default_text_llm(session, thinking=False)
            agent = ComplianceCheckerAgent(llm)
            report = await agent.a_check(
                script_text=script_text,
                region=region,
                product_category=product_category,
                script_duration_sec=duration,
                brand_aliases=brand_aliases,
            )

            persisted_findings = await _persist_findings(
                session, variant_id=variant_id, report=report
            )
            await store.set_progress(task_id, 80)

            output = _build_output_payload(variant_id=variant_id, report=report)
            await store.set_result(task_id, output)
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                variant_id=variant_id,
                score=report.score,
                findings_count=len(report.findings),
            )

            await _fire_blocker_dispatch(
                variant_id=variant_id,
                persisted_findings=persisted_findings,
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as fallback_session:
                fail_store = SqlAlchemyTaskStore(fallback_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await fallback_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "run_compliance_check_task",
]
