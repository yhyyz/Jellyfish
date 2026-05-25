"""W3-T3 合规规则引擎 + 内置规则集 + bootstrap 的功能性测试。

覆盖目标：
    1. 8 条 ``cn_mainland_default`` 规则的 GOLDEN CASE 命中/不命中（13 条）；
    2. 多规则同时触发不被互相吞掉（1 条）；
    3. ``bootstrap_builtin_compliance_profiles`` 全量插入 + 幂等回扫（2 条）；
    4. 性能 smoke：500 字脚本扫描 < 5ms（1 条）。

为什么放在 ``backend/tests/`` 顶层：
    与 ``test_builtin_prompts.py`` / ``test_compliance_smoke.py`` 同层级，
    便于 ``uv run pytest tests/`` 一次性发现。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.compliance import ComplianceProfile
from app.models.types import (
    ComplianceRegion,
    ComplianceSeverity,
    ProductCategory,
)
from app.services.compliance.bootstrap_compliance import (
    BUILTIN_COMPLIANCE_PROFILES,
    bootstrap_builtin_compliance_profiles,
)
from app.services.compliance.builtin_rules import (
    CN_MAINLAND_RULES,
    serialize_rules,
)
from app.services.compliance.rule_engine import (
    ComplianceFindingDTO,
    ComplianceRuleEngine,
)


# ---------------------------------------------------------------------------
# 引擎 fixture
# ---------------------------------------------------------------------------


def _make_engine() -> ComplianceRuleEngine:
    """构造一个装载完整 ``CN_MAINLAND_RULES`` 的引擎实例。"""

    return ComplianceRuleEngine(rules=CN_MAINLAND_RULES)


def _scan(
    text: str,
    *,
    product_category: ProductCategory = ProductCategory.other,
    duration_sec: int = 60,
    brand_aliases_override: tuple[str, ...] | None = None,
) -> list[ComplianceFindingDTO]:
    """统一 scan 入口，避免每个测试重复传 region/duration。"""

    return _make_engine().scan(
        text,
        region=ComplianceRegion.cn_mainland,
        product_category=product_category,
        script_duration_sec=duration_sec,
        brand_aliases_override=brand_aliases_override,
    )


# 基础"满足演绎标识"的合法脚本片段，用于不需要专门测 yanyi 的场景。
_LEGAL_LABEL = "本视频为演绎，"


# ---------------------------------------------------------------------------
# 1-2. 演绎/虚构 标识必须存在
# ---------------------------------------------------------------------------


def test_yanyi_label_blocks_when_missing() -> None:
    text = "今天给大家推荐一款不错的产品"
    findings = _scan(text)
    yanyi = [f for f in findings if f.rule_id == "cn_yanyi_label"]
    assert len(yanyi) == 1, "缺少 演绎/虚构 标识必须产出 1 个 finding"
    assert yanyi[0].severity == ComplianceSeverity.blocker


def test_yanyi_label_accepts_either_keyword() -> None:
    # "演绎"
    findings_yanyi = _scan(_LEGAL_LABEL + "随便聊聊产品。")
    assert all(f.rule_id != "cn_yanyi_label" for f in findings_yanyi)
    # "虚构"
    findings_xugou = _scan("本视频为剧情虚构，随便聊聊产品。")
    assert all(f.rule_id != "cn_yanyi_label" for f in findings_xugou)


# ---------------------------------------------------------------------------
# 3-4. 卖惨黑名单
# ---------------------------------------------------------------------------


def test_banned_maicai_detects_kuaiqiong_pattern() -> None:
    text = _LEGAL_LABEL + "我现在很穷，跪求大家买一单。"
    findings = _scan(text)
    maicai = [f for f in findings if f.rule_id == "cn_banned_maicai"]
    assert any(f.matched_text == "跪求" for f in maicai)
    assert all(f.severity == ComplianceSeverity.blocker for f in maicai)


def test_banned_maicai_detects_taican_pattern() -> None:
    text = _LEGAL_LABEL + "我太惨了，谁能帮帮我。"
    findings = _scan(text)
    maicai = [f for f in findings if f.rule_id == "cn_banned_maicai"]
    assert any(f.matched_text == "我太惨了" for f in maicai)


# ---------------------------------------------------------------------------
# 5. 伪造身份
# ---------------------------------------------------------------------------


def test_fake_credentials_warns_on_xidaxie() -> None:
    text = _LEGAL_LABEL + "我是悉尼大学的Linda教授，今天来推荐这款产品。"
    findings = _scan(text)
    creds = [f for f in findings if f.rule_id == "cn_banned_fake_credentials"]
    assert len(creds) >= 2, "应分别命中 '悉尼大学' 和 'Linda教授'"
    assert all(f.severity == ComplianceSeverity.warning for f in creds)


# ---------------------------------------------------------------------------
# 6. 群体丑化
# ---------------------------------------------------------------------------


def test_group_denigration_warns_on_nongcunren() -> None:
    text = _LEGAL_LABEL + "农村人就是不懂这种产品的好处。"
    findings = _scan(text)
    grp = [f for f in findings if f.rule_id == "cn_banned_group_denigration"]
    assert any(f.matched_text == "农村人" for f in grp)
    assert all(f.severity == ComplianceSeverity.warning for f in grp)


# ---------------------------------------------------------------------------
# 7. 品牌口播频次（运行期注入 brand_aliases）
# ---------------------------------------------------------------------------


def test_brand_mention_cap_warns_at_3_mentions_in_60s() -> None:
    text = _LEGAL_LABEL + "Acme 真好用，Acme 设计巧妙，Acme 是我的最爱。"
    findings = _scan(
        text,
        duration_sec=60,
        brand_aliases_override=("Acme",),
    )
    brand = [f for f in findings if f.rule_id == "cn_brand_mention_cap_60s"]
    assert len(brand) == 1
    assert brand[0].severity == ComplianceSeverity.warning
    assert brand[0].location == "mention_count:3"


def test_brand_mention_cap_does_not_warn_within_threshold() -> None:
    text = _LEGAL_LABEL + "Acme 真好用，Acme 设计巧妙。"
    findings = _scan(
        text,
        duration_sec=60,
        brand_aliases_override=("Acme",),
    )
    assert all(f.rule_id != "cn_brand_mention_cap_60s" for f in findings)


# ---------------------------------------------------------------------------
# 8-9. 健康类免责声明
# ---------------------------------------------------------------------------


def test_health_disclaimer_blocks_for_health_category_when_missing() -> None:
    text = _LEGAL_LABEL + "这款按摩仪每天用一次效果很好。"
    findings = _scan(text, product_category=ProductCategory.health)
    health = [f for f in findings if f.rule_id == "cn_health_disclaimer"]
    assert len(health) == 1
    assert health[0].severity == ComplianceSeverity.blocker


def test_health_disclaimer_does_not_apply_to_beauty_category() -> None:
    # 同样的脚本，对 beauty 品类不应触发健康免责（演绎标识仍然要满足）。
    text = _LEGAL_LABEL + "这款按摩仪每天用一次效果很好。"
    findings = _scan(text, product_category=ProductCategory.beauty)
    assert all(f.rule_id != "cn_health_disclaimer" for f in findings)


def test_health_disclaimer_satisfied_by_core_phrase() -> None:
    text = _LEGAL_LABEL + "这款按摩仪每天用一次，非医疗器械，请勿替代医生意见。"
    findings = _scan(text, product_category=ProductCategory.health)
    assert all(f.rule_id != "cn_health_disclaimer" for f in findings)


# ---------------------------------------------------------------------------
# 10. 不可验证宣称
# ---------------------------------------------------------------------------


def test_unverifiable_urgency_warns_on_jinxianxinri() -> None:
    text = _LEGAL_LABEL + "仅限今日，错过等10年。"
    findings = _scan(text)
    urgency = [f for f in findings if f.rule_id == "cn_unverifiable_urgency"]
    assert any(f.matched_text == "仅限今日" for f in urgency)
    assert any(f.matched_text == "错过等10年" for f in urgency)


# ---------------------------------------------------------------------------
# 11. 虚假政策宣称
# ---------------------------------------------------------------------------


def test_fake_policy_claim_blocks_on_guobu() -> None:
    text = _LEGAL_LABEL + "国补下线倒计时，赶紧下单。"
    findings = _scan(text)
    fake = [f for f in findings if f.rule_id == "cn_fake_policy_claim"]
    assert any(f.matched_text == "国补下线倒计时" for f in fake)
    assert all(f.severity == ComplianceSeverity.blocker for f in fake)


# ---------------------------------------------------------------------------
# 12. 干净脚本不触发任何规则
# ---------------------------------------------------------------------------


def test_clean_script_returns_empty_findings() -> None:
    text = _LEGAL_LABEL + "今天分享一个新产品，使用感受不错。"
    findings = _scan(text)
    assert findings == []


# ---------------------------------------------------------------------------
# 13. 不会重复计数同一关键词覆盖关系
# ---------------------------------------------------------------------------


def test_engine_does_not_double_count_overlapping_keywords() -> None:
    """同一规则同一模式只在出现处各计一次，不因 Aho-Corasick 子串覆盖而多算。"""

    text = _LEGAL_LABEL + "卖惨" * 3
    findings = _scan(text)
    maicai_hits = [
        f
        for f in findings
        if f.rule_id == "cn_banned_maicai" and f.matched_text == "卖惨"
    ]
    assert len(maicai_hits) == 3, "出现 3 次应当各产出 1 个 finding，不重复也不丢失"


# ---------------------------------------------------------------------------
# 冲突解决：多规则同时触发不互相吞噬
# ---------------------------------------------------------------------------


def test_multiple_rules_can_coexist_in_same_script() -> None:
    """脚本同时缺 演绎 标识 + 命中 卖惨 黑名单 -> 至少 2 个独立 finding。"""

    text = "今天太惨了，跪求大家买一单。"  # 没演绎，含 跪求 + 我太惨了的子串
    findings = _scan(text)
    rule_ids = {f.rule_id for f in findings}
    assert "cn_yanyi_label" in rule_ids
    assert "cn_banned_maicai" in rule_ids


# ---------------------------------------------------------------------------
# 14-15. Bootstrap 全量插入 + 幂等
# ---------------------------------------------------------------------------


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """创建一个内存 SQLite 异步 session，并建好 ORM 表。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


@pytest.mark.asyncio
async def test_bootstrap_inserts_cn_mainland_default_profile() -> None:
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_compliance_profiles(db)
        rows = (
            await db.execute(select(ComplianceProfile))
        ).scalars().all()

    await engine.dispose()

    assert stats == {
        "inserted": len(BUILTIN_COMPLIANCE_PROFILES),
        "updated": 0,
        "unchanged": 0,
    }
    assert len(rows) == len(BUILTIN_COMPLIANCE_PROFILES)
    profile = next(r for r in rows if r.id == "cn_mainland_default")
    assert profile.name == "中国大陆默认合规规则集"
    assert profile.region == ComplianceRegion.cn_mainland
    assert profile.is_system is True
    # 8 条规则应全部入库
    assert len(profile.rules) == len(CN_MAINLAND_RULES)
    assert profile.rules == serialize_rules(CN_MAINLAND_RULES)


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_compliance_profiles(db)
        second = await bootstrap_builtin_compliance_profiles(db)
        rows = (
            await db.execute(select(ComplianceProfile))
        ).scalars().all()

    await engine.dispose()

    assert first["inserted"] == len(BUILTIN_COMPLIANCE_PROFILES)
    assert second == {
        "inserted": 0,
        "updated": 0,
        "unchanged": len(BUILTIN_COMPLIANCE_PROFILES),
    }
    # 二次调用不重复写入
    assert len(rows) == len(BUILTIN_COMPLIANCE_PROFILES)


@pytest.mark.asyncio
async def test_bootstrap_repairs_drifted_profile() -> None:
    """手工改写一行后再次运行，会被纠回 canonical 版本。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_compliance_profiles(db)
        # 模拟运维误编辑：改名 + 清空 rules
        row = (
            await db.execute(
                select(ComplianceProfile).where(
                    ComplianceProfile.id == "cn_mainland_default"
                )
            )
        ).scalar_one()
        row.name = "MUTATED"
        row.rules = []
        await db.commit()

        stats = await bootstrap_builtin_compliance_profiles(db)
        repaired = (
            await db.execute(
                select(ComplianceProfile).where(
                    ComplianceProfile.id == "cn_mainland_default"
                )
            )
        ).scalar_one()

    await engine.dispose()

    assert stats == {"inserted": 0, "updated": 1, "unchanged": 0}
    assert repaired.name == "中国大陆默认合规规则集"
    assert len(repaired.rules) == len(CN_MAINLAND_RULES)


# ---------------------------------------------------------------------------
# 16. 性能 smoke：500 字脚本扫描 < 5ms（中位数取 5 次最小值）
# ---------------------------------------------------------------------------


def test_engine_scans_500_word_script_under_5ms() -> None:
    """在 500 字脚本上跑 5 次，最小耗时必须 < 5ms。

    用最小值过滤 GC/CI 抖动；阈值留足余量但仍能锁住 regex 退化（regex 通常
    在 20+ 模式时 50-100ms）。
    """

    base_chunk = "今天本视频为演绎，分享一款不错的产品，体验很好，建议大家试一下。"
    # 拼到约 500 字（每段 30 字 * 17 = 510 字）。
    text = base_chunk * 17
    engine = _make_engine()

    durations: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        engine.scan(
            text,
            region=ComplianceRegion.cn_mainland,
            product_category=ProductCategory.other,
            script_duration_sec=60,
            brand_aliases_override=("Acme",),
        )
        durations.append(time.perf_counter() - start)

    best_ms = min(durations) * 1000
    assert best_ms < 5.0, f"500 字脚本扫描最快应 < 5ms，实际 {best_ms:.3f}ms"
