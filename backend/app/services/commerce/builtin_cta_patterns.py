"""系统级 CTA 模式（CtaPattern）种子数据加载器（W11-T2，P2 准备阶段）。

本模块提供两个东西：

1. ``BUILTIN_CTA_PATTERN_DEFINITIONS``：5 条 CTA 模式定义，按 hardness ×
   urgency_type 二维分类（``scarcity_cta`` / ``social_proof_cta`` /
   ``benefit_direct_cta`` / ``risk_removal_cta`` / ``urgency_simple_cta``）。
2. ``bootstrap_builtin_cta_patterns(db)``：启动时调用的幂等加载函数，把
   定义同步到 ``cta_patterns`` 表（INSERT/UPDATE/UNCHANGED 三态计数，
   ``is_system=True``）。

设计原则与边界：

- 与 :mod:`builtin_hook_patterns` 同构：系统级注册表 + Pydantic 类型化 +
  vocabulary 校验；
- 双轴 vocabulary 分别用 :data:`KNOWN_HARDNESS` 与 :data:`KNOWN_URGENCY_TYPES`
  约束，新增分类必须扩 vocabulary 并同步到前端筛选与 Wave 13 文档；
- ``sample_phrases`` 至少给 5 条样例，避免投放风格雷同；
- 不在本期与 ``StoryVariant.cta_pattern_id`` 建立硬外键。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cta_pattern import CtaPattern


# ---------------------------------------------------------------------------
# 词汇表：硬度等级 + 驱动类型
# ---------------------------------------------------------------------------

#: CTA 硬度等级。``soft``=温和邀请；``medium``=明确建议；``hard``=直接呼喊。
KNOWN_HARDNESS: frozenset[str] = frozenset({"soft", "medium", "hard"})

#: CTA 驱动类型，决定底层心理机制：
#: - ``scarcity``：库存稀缺驱动
#: - ``urgency``：时间窗口驱动
#: - ``social_proof``：从众/社会认同驱动
#: - ``benefit``：直击利益驱动
#: - ``risk_removal``：去除使用风险驱动
KNOWN_URGENCY_TYPES: frozenset[str] = frozenset(
    {"scarcity", "urgency", "social_proof", "benefit", "risk_removal"}
)


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


class CtaPatternDefinition(BaseModel):
    """单条系统级 CTA 定义。

    字段与 :class:`app.models.cta_pattern.CtaPattern` 一一对齐，便于
    bootstrap 直接映射 ORM 字段；额外保留 ``sample_phrases`` 用于运营
    层抽样投放。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    hardness: str = Field(..., min_length=1, max_length=16)
    urgency_type: str = Field(..., min_length=1, max_length=32)
    description: str = Field(..., min_length=1)
    template_text: str = Field(..., min_length=1)
    sample_phrases: list[str] = Field(..., min_length=5)
    is_system: bool = True
    sort_order: int = Field(..., ge=0)

    @field_validator("hardness")
    @classmethod
    def _validate_hardness(cls, value: str) -> str:
        """约束 ``hardness`` 仅允许 :data:`KNOWN_HARDNESS` 成员。"""
        if value not in KNOWN_HARDNESS:
            raise ValueError(
                f"unknown hardness {value!r}; allowed: {sorted(KNOWN_HARDNESS)}"
            )
        return value

    @field_validator("urgency_type")
    @classmethod
    def _validate_urgency_type(cls, value: str) -> str:
        """约束 ``urgency_type`` 仅允许 :data:`KNOWN_URGENCY_TYPES` 成员。"""
        if value not in KNOWN_URGENCY_TYPES:
            raise ValueError(
                f"unknown urgency_type {value!r}; "
                f"allowed: {sorted(KNOWN_URGENCY_TYPES)}"
            )
        return value


# ---------------------------------------------------------------------------
# 5 条系统级 CTA（按 sort_order 升序）
# ---------------------------------------------------------------------------


_SCARCITY_CTA = CtaPatternDefinition(
    id="scarcity_cta",
    name="稀缺紧迫",
    hardness="hard",
    urgency_type="scarcity",
    description=(
        "强调“库存有限/名额有限/限定批次”，让观众感觉再不下单就失去机会。"
        "稀缺 CTA 是中国直播间和短视频信息流转化效率最高的 CTA 之一，但"
        "合规成本相对高——要求“稀缺”必须真实可验证，禁止持续虚假“剩 X"
        "件“。建议在脚本里写清”截止时间“或”批次编号“等可核查信号，避免"
        "广告法举报。"
    ),
    template_text=(
        "{{ character }}（拿起 {{ product_name }} 对镜头）：\n"
        "今天这一批只有 {{ stock_count }} 件——卖完真的就没了。\n"
        "字幕：仅剩 {{ stock_count }} 件 · 售完不再补货"
    ),
    sample_phrases=[
        "仅剩 {stock} 件，卖完不补",
        "本批次今晚 24:00 截止",
        "限定 {region} 地区发货",
        "首发批次仅 {stock} 套",
        "明天这个价格就没有了",
        "今天链接里就这一批库存",
    ],
    sort_order=10,
)


_SOCIAL_PROOF_CTA = CtaPatternDefinition(
    id="social_proof_cta",
    name="社会认同",
    hardness="medium",
    urgency_type="social_proof",
    description=(
        "用“已经有 N 个人这样做了”建立从众心理。社会认同 CTA 比稀缺型温"
        "和，转化窗口更长，更适合“先种草后转化”的内容。它依赖具体可信"
        "的数字（“已售 12 万+”、“5000 个宝妈推荐”），数字必须真实，因为"
        "一旦数据被证伪，整体可信度比稀缺型 CTA 受损更严重。"
    ),
    template_text=(
        "{{ character }}（看向镜头）：\n"
        "我不是第一个用 {{ product_name }} 的，已经有 {{ user_count }} "
        "个朋友先我一步——\n"
        "字幕：{{ user_count }}+ 用户已选择"
    ),
    sample_phrases=[
        "已售 {count}+ 件",
        "{count} 个宝妈在用",
        "回购率 {rate}%",
        "好评率 {rate}%",
        "{count} 万人推荐",
        "今年最受欢迎的 {category}",
    ],
    sort_order=20,
)


_BENEFIT_DIRECT_CTA = CtaPatternDefinition(
    id="benefit_direct_cta",
    name="利益直击",
    hardness="medium",
    urgency_type="benefit",
    description=(
        "直接告诉观众“下单可以得到什么”——具体的利益（赠品、折扣、增值"
        "服务、联名礼盒）。利益直击 CTA 的核心是“利益要够具体、够即时、"
        "够可见“。”满 199 减 30“远比”今天有优惠“有效；”加赠同色补充装"
        "比“赠品丰厚”有效。这种 CTA 在新客冷启动场景效率最高。"
    ),
    template_text=(
        "（产品旁边出现赠品镜头）\n"
        "字幕：今晚下单，加赠 {{ bonus_item }}\n"
        "{{ character }}（笑）：算下来比平时便宜 {{ saving_amount }}。"
    ),
    sample_phrases=[
        "下单立减 {amount}",
        "买一送一",
        "加赠 {bonus}",
        "前 {n} 名加赠定制礼盒",
        "今天领券再 -{amount}",
        "组合装直降 {amount}",
    ],
    sort_order=30,
)


_RISK_REMOVAL_CTA = CtaPatternDefinition(
    id="risk_removal_cta",
    name="风险消除",
    hardness="soft",
    urgency_type="risk_removal",
    description=(
        "通过“30 天无理由退换”“不满意全额退款”“免费试用”等方式把决策风"
        "险拿走。风险消除 CTA 是高客单价、新品类、新品牌冷启动时的最"
        "佳选择——观众的拒绝理由从“我担心买错”变成“反正我没有损失”，决"
        "策门槛被显著降低。但前提是品牌真的能兑现承诺，否则“无理由”反"
        "而成为信任坍塌的导火索。"
    ),
    template_text=(
        "{{ character }}（拿着包装盒，对镜头）：\n"
        "怕踩雷？{{ product_name }} 支持 {{ guarantee_period }} 内无理由退换。\n"
        "字幕：{{ guarantee_period }} 不满意 · 全额退"
    ),
    sample_phrases=[
        "30 天无理由退换",
        "不满意全额退款",
        "首次免费试用 7 天",
        "假一赔十",
        "退货运费由商家承担",
        "买贵差价双倍补",
    ],
    sort_order=40,
)


_URGENCY_SIMPLE_CTA = CtaPatternDefinition(
    id="urgency_simple_cta",
    name="限时促销",
    hardness="hard",
    urgency_type="urgency",
    description=(
        "用一个明确的时间窗（“今晚 8 点截止”、“周末过后涨价”）制造紧迫"
        "感。限时促销 CTA 与稀缺型相似但驱动机制不同：稀缺靠“库存少”，"
        "限时靠“窗口短”。它的最大优势是合规相对清晰——只要时间真实可"
        "验证，并在画面给出倒计时或截止时刻字幕，就比“剩 X 件”更稳。建"
        "议在快闪促销、双 11/618 等节点优先选用。"
    ),
    template_text=(
        "（屏幕右上角倒计时浮起）\n"
        "{{ character }}：到 {{ deadline }} 这个价格就没了。\n"
        "字幕：限时至 {{ deadline }} · 错过等明年"
    ),
    sample_phrases=[
        "今晚 24:00 截止",
        "限时 48 小时",
        "本周末过后恢复原价",
        "618 最后一天",
        "倒计时 {hours} 小时",
        "明天恢复原价 {price}",
    ],
    sort_order=50,
)


#: 全量内置 CTA 定义，顺序即 ``sort_order`` 升序：
#: 1. scarcity_cta（稀缺紧迫，hard × scarcity）
#: 2. social_proof_cta（社会认同，medium × social_proof）
#: 3. benefit_direct_cta（利益直击，medium × benefit）
#: 4. risk_removal_cta（风险消除，soft × risk_removal）
#: 5. urgency_simple_cta（限时促销，hard × urgency）
BUILTIN_CTA_PATTERN_DEFINITIONS: list[CtaPatternDefinition] = [
    _SCARCITY_CTA,
    _SOCIAL_PROOF_CTA,
    _BENEFIT_DIRECT_CTA,
    _RISK_REMOVAL_CTA,
    _URGENCY_SIMPLE_CTA,
]


# ---------------------------------------------------------------------------
# 幂等加载器
# ---------------------------------------------------------------------------


def _definition_to_orm_kwargs(definition: CtaPatternDefinition) -> dict[str, Any]:
    """把 :class:`CtaPatternDefinition` 转成 :class:`CtaPattern` 字段字典。"""
    return {
        "id": definition.id,
        "name": definition.name,
        "hardness": definition.hardness,
        "urgency_type": definition.urgency_type,
        "description": definition.description,
        "template_text": definition.template_text,
        "sample_phrases": list(definition.sample_phrases),
        "is_system": definition.is_system,
        "sort_order": definition.sort_order,
    }


def _diff_orm_against_payload(
    existing: CtaPattern, payload: dict[str, Any]
) -> bool:
    """判断 ORM 行是否与目标字段一致；返回 ``True`` 即需要 UPDATE。"""
    for key, expected in payload.items():
        if key == "id":
            continue
        if getattr(existing, key) != expected:
            return True
    return False


async def bootstrap_builtin_cta_patterns(
    db: AsyncSession,
) -> dict[str, int]:
    """启动时调用，幂等地确保 5 条内置 CTA 模式存在于 ``cta_patterns`` 表中。

    幂等策略与 :func:`bootstrap_builtin_hook_patterns` 一致（id 为业务
    键、INSERT/UPDATE/UNCHANGED 三态计数），便于 :mod:`app.bootstrap` 统一
    汇总启动统计。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}``，三者之和等于
        :data:`BUILTIN_CTA_PATTERN_DEFINITIONS` 的长度（当前为 5）。
    """
    counters: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}

    for definition in BUILTIN_CTA_PATTERN_DEFINITIONS:
        payload = _definition_to_orm_kwargs(definition)
        existing = await db.get(CtaPattern, definition.id)

        if existing is None:
            db.add(CtaPattern(**payload))
            counters["inserted"] += 1
            continue

        if _diff_orm_against_payload(existing, payload):
            for key, value in payload.items():
                if key == "id":
                    continue
                setattr(existing, key, value)
            counters["updated"] += 1
        else:
            counters["unchanged"] += 1

    await db.commit()
    return counters


__all__ = [
    "CtaPatternDefinition",
    "BUILTIN_CTA_PATTERN_DEFINITIONS",
    "KNOWN_HARDNESS",
    "KNOWN_URGENCY_TYPES",
    "bootstrap_builtin_cta_patterns",
]
