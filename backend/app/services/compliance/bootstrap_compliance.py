"""系统级 :class:`ComplianceProfile` 内置启动注册（idempotent bootstrap）。

为什么存在：
    剧情带货合规链路从 P1 引入 ``cn_mainland_default``，W11-T4 起扩展到
    ``cn_mainland_health`` / ``overseas_default``。它们均为系统预置
    （``is_system=True``）数据，必须在应用首次启动后落地到
    ``compliance_profiles`` 表，且重复启动不重复写入。本模块即为该 seed
    流程的承载点。

做什么：
    暴露 :func:`bootstrap_builtin_compliance_profiles`，由
    :func:`app.bootstrap.bootstrap_async_state` 在 FastAPI ``lifespan`` 中调用：
        1. 按 ``id`` 查询是否已存在；
        2. 缺则插入；存在但内容漂移则覆盖回 canonical；完全一致则跳过；
        3. 一次性 ``commit()``。

幂等性契约：
    SELECT id WHERE id=<profile.id>
        if exists & 内容完全一致 -> "unchanged"
        if exists & 任一字段不同 -> "updated"
        else                     -> "inserted"

边界：
    - 当前注入 3 个 profile：``cn_mainland_default`` /
      ``cn_mainland_health`` / ``overseas_default``。``hk_tw`` 暂未提供，
      留给后续 plan；
    - 与 :func:`app.services.studio.builtin_prompts.bootstrap_builtin_prompts`
      共用 :class:`AsyncSession`，调用顺序由 :mod:`app.bootstrap` 维护：
      ``prompts -> formulas -> compliance``。
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import ComplianceProfile
from app.services.compliance.builtin_rules import (
    CN_MAINLAND_DEFAULT_PROFILE,
    CN_MAINLAND_HEALTH_PROFILE,
    OVERSEAS_DEFAULT_PROFILE,
    ComplianceProfileDefinition,
    serialize_rules,
)

# ---------------------------------------------------------------------------
# 注册表 —— 当前注入 3 个内置 profile
# ---------------------------------------------------------------------------

BUILTIN_COMPLIANCE_PROFILES: tuple[ComplianceProfileDefinition, ...] = (
    CN_MAINLAND_DEFAULT_PROFILE,
    CN_MAINLAND_HEALTH_PROFILE,
    OVERSEAS_DEFAULT_PROFILE,
)


# ---------------------------------------------------------------------------
# 内部对比/同步辅助
# ---------------------------------------------------------------------------


def _serialized_payload(definition: ComplianceProfileDefinition) -> dict[str, Any]:
    """构造一行 ``compliance_profiles`` 的目标"应当是什么"快照。"""

    return {
        "id": definition.id,
        "name": definition.name,
        "region": definition.region,
        "description": definition.description,
        "rules": serialize_rules(definition.rules),
        "is_system": True,
    }


def _is_same(record: ComplianceProfile, definition: ComplianceProfileDefinition) -> bool:
    """比较 DB 行与定义是否完全一致；用于决定 unchanged vs updated。

    rules 列存 JSON，先序列化成同一形态再做相等性比较，避免因为字段顺序、
    tuple/list、枚举/字符串等差异误判。
    """

    expected_rules = serialize_rules(definition.rules)
    return (
        record.name == definition.name
        and record.region == definition.region
        and record.description == definition.description
        and record.rules == expected_rules
        and bool(record.is_system) is True
    )


def _apply_definition(
    record: ComplianceProfile,
    definition: ComplianceProfileDefinition,
) -> None:
    """把 :class:`ComplianceProfileDefinition` 字段同步到一行 ORM 记录上。"""

    record.name = definition.name
    record.region = definition.region
    record.description = definition.description
    record.rules = serialize_rules(definition.rules)
    record.is_system = True


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


async def bootstrap_builtin_compliance_profiles(
    db: AsyncSession,
    *,
    profiles: Iterable[ComplianceProfileDefinition] | None = None,
) -> dict[str, int]:
    """启动时调用，幂等地确保系统级 :class:`ComplianceProfile` 都存在。

    Args:
        db: 已绑定到目标库的 :class:`AsyncSession`；本函数只对
            ``compliance_profiles`` 表读 / 写，并在最后一次性 ``commit()``。
        profiles: 可选的 profile 列表覆盖（测试时传自定义集合）；默认使用
            :data:`BUILTIN_COMPLIANCE_PROFILES`。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}`` 计数字典，方便
        启动日志直接打印或被测试断言。
    """

    target_profiles = (
        tuple(profiles) if profiles is not None else BUILTIN_COMPLIANCE_PROFILES
    )

    inserted = 0
    updated = 0
    unchanged = 0

    for definition in target_profiles:
        stmt = select(ComplianceProfile).where(ComplianceProfile.id == definition.id)
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing is None:
            payload = _serialized_payload(definition)
            new_row = ComplianceProfile(**payload)
            db.add(new_row)
            inserted += 1
            continue

        if _is_same(existing, definition):
            unchanged += 1
            continue

        _apply_definition(existing, definition)
        updated += 1

    await db.commit()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


__all__ = [
    "BUILTIN_COMPLIANCE_PROFILES",
    "bootstrap_builtin_compliance_profiles",
]
