"""W6-T3: ``GET /studio/compliance/*`` 只读端点端到端测试。

测试策略
--------

- 使用文件型 SQLite + ``Base.metadata.create_all`` 建表，覆盖
  ``compliance_profiles`` / ``compliance_findings`` / ``story_variants``
  / ``story_formulas`` / ``projects`` / ``chapters`` 等模型；
- 通过 :func:`bootstrap_builtin_compliance_profiles` 真实写入
  ``cn_mainland_default``，避免在测试里手工拼 rules JSON；
- 通过 ``app.dependency_overrides`` 覆盖 ``get_db``，让路由命中测试库；
- 直接构造 :class:`ComplianceFinding` 行验证 finding 列表过滤。

覆盖点
------

* GET /studio/compliance/profiles                          ✓ ``cn_mainland_default``
* GET /studio/compliance/profiles?region=cn_mainland       ✓ region 过滤
* GET /studio/compliance/profiles/{id}                     ✓ 完整 rules JSON
* GET /studio/compliance/profiles/{id}                     ✓ 404 missing
* GET /studio/compliance/findings?variant_id=X             ✓ 列表
* GET /studio/compliance/findings?severity=blocker         ✓ 严重度过滤
* GET /studio/compliance/findings?is_resolved=false        ✓ 解决态过滤
* GET /studio/compliance/findings 200 empty                ✓ 无 finding 时返回空数组
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.compliance import ComplianceFinding
from app.models.types import ComplianceSeverity
from app.services.compliance.bootstrap_compliance import (
    bootstrap_builtin_compliance_profiles,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    db_path = tmp_path / "compliance-query.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sm() as db:
            await bootstrap_builtin_compliance_profiles(db)

    asyncio.run(_create_all())
    try:
        yield sm
    finally:
        async def _dispose() -> None:
            await engine.dispose()

        asyncio.run(_dispose())


@pytest.fixture
def client_with_db(session_local) -> Generator[TestClient, None, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_findings(session_local, variant_id: str = "var-1") -> None:
    """构造若干 ``ComplianceFinding`` 行用于过滤测试。

    为了避免依赖 ``story_variants`` / ``story_formulas`` / ``projects``
    等父表的真实数据（外键关系复杂），这里关闭 SQLite 的外键约束再 INSERT。
    """

    async def _seed() -> None:
        async with session_local() as db:
            await db.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys = OFF"))
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add_all(
                [
                    ComplianceFinding(
                        variant_id=variant_id,
                        severity=ComplianceSeverity.blocker,
                        rule_id="cn_yanyi_label",
                        rule_kind="required_label",
                        description="缺少演绎标签",
                        location="Shot 1",
                        suggested_fix="添加'演绎'标签",
                        is_resolved=False,
                        detected_at=now,
                    ),
                    ComplianceFinding(
                        variant_id=variant_id,
                        severity=ComplianceSeverity.warning,
                        rule_id="cn_banned_fake_credentials",
                        rule_kind="banned_phrase",
                        description="伪造身份疑似命中",
                        location="Shot 2",
                        suggested_fix=None,
                        is_resolved=True,
                        detected_at=now,
                    ),
                    ComplianceFinding(
                        variant_id=variant_id,
                        severity=ComplianceSeverity.info,
                        rule_id="cn_brand_cap",
                        rule_kind="brand_mention_cap",
                        description="品牌口播频次接近上限",
                        location=None,
                        suggested_fix=None,
                        is_resolved=False,
                        detected_at=now,
                    ),
                ]
            )
            await db.commit()

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# Tests: GET /studio/compliance/profiles
# ---------------------------------------------------------------------------


def test_list_profiles_returns_cn_mainland_default_after_seed(client_with_db) -> None:
    resp = client_with_db.get("/api/v1/studio/compliance/profiles")
    assert resp.status_code == 200

    body = resp.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)

    profile_ids = [p["id"] for p in body["data"]]
    assert "cn_mainland_default" in profile_ids

    cn = next(p for p in body["data"] if p["id"] == "cn_mainland_default")
    assert cn["region"] == "cn_mainland"
    assert cn["is_system"] is True
    assert isinstance(cn["rules"], list) and len(cn["rules"]) > 0


def test_list_profiles_filters_by_region(client_with_db) -> None:
    resp = client_with_db.get("/api/v1/studio/compliance/profiles?region=cn_mainland")
    assert resp.status_code == 200
    body = resp.json()
    assert all(p["region"] == "cn_mainland" for p in body["data"])
    assert any(p["id"] == "cn_mainland_default" for p in body["data"])

    resp_other = client_with_db.get("/api/v1/studio/compliance/profiles?region=overseas")
    assert resp_other.status_code == 200
    assert resp_other.json()["data"] == []


def test_get_profile_returns_full_rules_json(client_with_db) -> None:
    resp = client_with_db.get("/api/v1/studio/compliance/profiles/cn_mainland_default")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == "cn_mainland_default"
    assert isinstance(body["data"]["rules"], list)
    assert len(body["data"]["rules"]) > 0
    rule_ids = {r.get("id") for r in body["data"]["rules"]}
    assert "cn_yanyi_label" in rule_ids


def test_get_profile_returns_404_when_missing(client_with_db) -> None:
    resp = client_with_db.get("/api/v1/studio/compliance/profiles/does_not_exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /studio/compliance/findings
# ---------------------------------------------------------------------------


def test_list_findings_returns_findings_for_variant(client_with_db, session_local) -> None:
    _seed_findings(session_local, variant_id="var-1")

    resp = client_with_db.get("/api/v1/studio/compliance/findings?variant_id=var-1")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 3
    assert {f["rule_id"] for f in body["data"]} == {
        "cn_yanyi_label",
        "cn_banned_fake_credentials",
        "cn_brand_cap",
    }


def test_list_findings_filters_by_severity_blocker(
    client_with_db, session_local
) -> None:
    _seed_findings(session_local, variant_id="var-1")

    resp = client_with_db.get(
        "/api/v1/studio/compliance/findings?variant_id=var-1&severity=blocker"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["severity"] == "blocker"
    assert body["data"][0]["rule_id"] == "cn_yanyi_label"


def test_list_findings_filters_by_is_resolved_false(
    client_with_db, session_local
) -> None:
    _seed_findings(session_local, variant_id="var-1")

    resp = client_with_db.get(
        "/api/v1/studio/compliance/findings?variant_id=var-1&is_resolved=false"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    for f in body["data"]:
        assert f["is_resolved"] is False


def test_list_findings_returns_200_empty_when_no_findings(client_with_db) -> None:
    resp = client_with_db.get(
        "/api/v1/studio/compliance/findings?variant_id=does-not-exist"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
