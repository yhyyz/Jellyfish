"""系统级音色包 seed（P3 W17 引入；P5 W29 加海外音色 spec 注册表）。

为什么存在：
    P3 W17 起 TTS 链路统一走 ``VoicePack`` 抽象，前端音色选择器与
    后端 dispatcher 都依赖一份"系统默认可用"的内置音色清单。该
    清单不应依赖人工 SQL，而要随应用启动自动到位（与
    ``builtin_prompts`` 风格保持一致）。

    P5 W29 起新增"海外档"概念：与 zh-CN 内置档（``_BUILTIN``）并列，
    在 :data:`OVERSEAS_VOICE_SPECS` 维护 6 条 en/ja/ko 海外音色 spec，
    供 ``backend/scripts/seed_overseas_voice_packs.py`` 走
    :mod:`app.services.studio.voice_clone_service` 同管线创建（用户禁
    止"绕过平台契约"——即不允许直接 INSERT 一个未经 DashScope 验证的
    voice_id）。本模块**不会** 在 startup 自动 seed 海外档，只负责
    集中维护 spec 列表，让脚本与未来管理面板有单一可信源。

做什么：
    ``bootstrap_builtin_voice_packs(db)`` 在应用启动时被调用：
      * 写入 6 个 zh-CN cosyvoice-v2 内置音色包；
      * 幂等：以主键 ``id`` 定位，不存在则 INSERT，存在但有差异则
        UPDATE 名称 / 描述 / 性别 / 排序 / archetype hint，相同则跳过；
      * 全部标记 ``is_system=True``，业务侧不允许删除；
      * ``sort_order`` 按枚举顺序递增（中性 0、男 10、女 20、少年 30、
        中年 40、老者 50），便于前端按"风格档"分组展示。

幂等性契约：
    SELECT id WHERE id=spec.id
        if exists & 全字段一致 -> "unchanged"
        if exists & 任一字段不同 -> "updated"（覆盖回 spec）
        else -> "inserted"

调用方：``app.bootstrap.bootstrap_async_state``（FastAPI lifespan 内）。

请勿手工修改本文件中音色包的 ``id`` 与 ``provider_voice_id``：
    它们与阿里云 DashScope 官方音色 ID 一一对应，被 dispatcher
    与缓存 key 共同消费，错值会导致 TTS 调用失败或缓存击穿。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.types import VoiceGender, VoiceProvider
from app.models.voice_pack import VoicePack


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuiltinVoicePackSpec:
    """单个内置音色包定义（不可变）。

    字段含义：
        id: 数据库主键；命名约定 ``cosyvoice_v2_<provider_voice_id_short>``。
        name: UI 展示名；中文短名，与官方音色昵称保持一致。
        provider_voice_id: DashScope 官方 voice id；务必与官方文档一致，
            longxiaochun 带 ``_v2`` 后缀，其余 5 个不带（这是官方现状）。
        gender: 性别枚举，前端用于“风格档”分组。
        description: 用户可见的简要说明，含人设定位与适用场景。
        sort_order: 排序权重，越小越靠前；中性档 0，男声档 10，女声档
            20，少年档 30，中年男档 40，老者档 50。
        archetype_hint: 与品牌 archetype 体系的弱关联建议；可空。
            仅用于“按品牌人格自动推荐音色”的兜底策略，不是硬绑定。
    """

    id: str
    name: str
    provider_voice_id: str
    gender: VoiceGender
    description: str
    sort_order: int
    archetype_hint: str | None = None


# ---------------------------------------------------------------------------
# 注册表（6 个内置音色包，顺序即 sort_order 顺序）
# ---------------------------------------------------------------------------


_BUILTIN: Final[list[_BuiltinVoicePackSpec]] = [
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longxiaochun",
        name="龙小淳",
        provider_voice_id="longxiaochun_v2",
        gender=VoiceGender.neutral,
        description="知性积极，语音助手标杆，性别中性可用于旁白与品牌人格代言",
        sort_order=0,
        archetype_hint="sage",
    ),
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longanlang",
        name="龙安朗",
        provider_voice_id="longanlang",
        gender=VoiceGender.male,
        description="清爽利落男声，适合年轻男性主角",
        sort_order=10,
    ),
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longanwen",
        name="龙安温",
        provider_voice_id="longanwen",
        gender=VoiceGender.female,
        description="优雅知性女声，适合都市女性主角",
        sort_order=20,
    ),
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longniuniu",
        name="龙牛牛",
        provider_voice_id="longniuniu",
        gender=VoiceGender.child,
        description="阳光男童声，适合少年角色",
        sort_order=30,
    ),
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longsanshu",
        name="龙三叔",
        provider_voice_id="longsanshu",
        gender=VoiceGender.male,
        description="沉稳质感中年男声（25-45 岁），适合家庭/职场剧情主角",
        sort_order=40,
        archetype_hint="expert",
    ),
    _BuiltinVoicePackSpec(
        id="cosyvoice_v2_longlaobo",
        name="龙老伯",
        provider_voice_id="longlaobo",
        gender=VoiceGender.male,
        description="沧桑岁月爷（60岁以上），适合长者/旁白叙事",
        sort_order=50,
        archetype_hint="sage",
    ),
]


# ---------------------------------------------------------------------------
# 启动函数
# ---------------------------------------------------------------------------


async def bootstrap_builtin_voice_packs(db: AsyncSession) -> dict[str, int]:
    """启动时调用，幂等地确保 6 个系统级音色包存在并保持 canonical。

    幂等策略：
        以主键 ``id`` 查询已有记录：
            * 命中 + 字段全部一致 -> ``unchanged`` 计数；
            * 命中 + 任一字段不同 -> ``updated`` 计数（覆盖回 spec）；
              注意：``provider_voice_id`` / ``language_code`` /
              ``provider`` 视为不变量，本函数不会去“修复”它们——
              如果出现这些字段不一致，说明业务在用同一个 ``id`` 复用
              记录，应在上游修复，而不是默默改写；
            * 未命中 -> ``inserted`` 计数（按 spec 新插入）。

    用户自定义音色（``is_system=False``）不在本函数管辖范围内：
        seed 只负责系统行；用户复刻 / 上传的音色生命周期由
        VoicePackService 单独管理。

    Args:
        db: 已绑定到目标库的 AsyncSession；本函数只对 ``voice_packs``
            表做读 / 写，并在最后一次性 ``commit()``。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}`` 计数字典，
        便于启动日志直接打印或被测试断言；保持与
        ``bootstrap_builtin_prompts`` 同形契约。
    """

    inserted = 0
    updated = 0
    unchanged = 0

    for spec in _BUILTIN:
        existing = await db.get(VoicePack, spec.id)
        if existing is None:
            db.add(
                VoicePack(
                    id=spec.id,
                    name=spec.name,
                    provider=VoiceProvider.aliyun_cosyvoice,
                    provider_voice_id=spec.provider_voice_id,
                    language_code="zh-CN",
                    gender=spec.gender,
                    archetype_hint=spec.archetype_hint,
                    description=spec.description,
                    default_speed=1.0,
                    is_system=True,
                    sort_order=spec.sort_order,
                )
            )
            inserted += 1
            continue

        if _is_same(existing, spec):
            unchanged += 1
            continue

        _apply_spec(existing, spec)
        updated += 1

    await db.commit()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_same(record: VoicePack, spec: _BuiltinVoicePackSpec) -> bool:
    """比较 DB 行与 spec 是否完全一致；用于决定 unchanged vs updated。

    可变字段：``name`` / ``description`` / ``gender`` / ``sort_order`` /
    ``archetype_hint``。``provider_voice_id`` / ``language_code`` /
    ``provider`` / ``is_system`` 视为不变量，不参与幂等比较。
    """

    return (
        record.name == spec.name
        and record.description == spec.description
        and _gender_equals(record.gender, spec.gender)
        and record.sort_order == spec.sort_order
        and record.archetype_hint == spec.archetype_hint
    )


def _apply_spec(record: VoicePack, spec: _BuiltinVoicePackSpec) -> None:
    """把 spec 的可变字段同步到一行 ORM 记录上。

    见 ``_is_same`` 注释：本函数不修改 ``provider_voice_id`` 等不变量，
    避免误修复上游异常。
    """

    record.name = spec.name
    record.description = spec.description
    record.gender = spec.gender
    record.sort_order = spec.sort_order
    record.archetype_hint = spec.archetype_hint


def _gender_equals(left: object, right: VoiceGender) -> bool:
    """容忍 SQLAlchemy 不同后端对 Enum 列返回的 str / Enum 差异。

    SQLite 把 Enum 列以原始字符串返回，MySQL 在 ``native_enum=True``
    下返回 Enum 实例；统一比较 ``.value`` 即可。
    """

    if isinstance(left, VoiceGender):
        return left == right
    return str(left) == right.value


# ---------------------------------------------------------------------------
# 海外音色 spec 注册表（P5 W29 引入；不在 startup 自动 seed）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OverseasVoiceSpec:
    """海外档音色 spec（不可变；与 zh-CN ``_BuiltinVoicePackSpec`` 并列）。

    与 ``_BuiltinVoicePackSpec`` 的区别：
        - ``provider_voice_id`` 不在此列举：海外档由
          ``backend/scripts/seed_overseas_voice_packs.py`` 走 voice_clone_service
          同管线动态创建后填回 DB，确保 ID 真实来自 DashScope；
        - 多了 ``language_code`` / ``language_hint`` / ``prefix`` 字段，对应
          DashScope create_voice 入参。

    Attributes:
        id: VoicePack 主键；命名约定 ``cosyvoice_v3_<lang>_<archetype>``。
        name: UI 展示名称（多语言）。
        prefix: DashScope create_voice 用的 ≤10 字符 slug（仅英数字下划线）。
        language_code: 与 ``VoicePack.language_code`` 一致（``en-US`` / ``ja-JP`` / ``ko-KR``）。
        language_hint: DashScope 接受的 ISO 码（``en`` / ``ja`` / ``ko``）。
        gender: 性别枚举。
        description: 用户可见的简短说明。
    """

    id: str
    name: str
    prefix: str
    language_code: str
    language_hint: str
    gender: VoiceGender
    description: str


OVERSEAS_VOICE_SPECS: Final[list[_OverseasVoiceSpec]] = [
    _OverseasVoiceSpec(
        id="cosyvoice_v3_en_warm_male",
        name="Warm Male (English)",
        prefix="enwarmmal",
        language_code="en-US",
        language_hint="en",
        gender=VoiceGender.male,
        description="Warm, conversational male English voice for storytelling.",
    ),
    _OverseasVoiceSpec(
        id="cosyvoice_v3_en_bright_female",
        name="Bright Female (English)",
        prefix="enbrtfem",
        language_code="en-US",
        language_hint="en",
        gender=VoiceGender.female,
        description="Bright, upbeat female English voice for product hooks.",
    ),
    _OverseasVoiceSpec(
        id="cosyvoice_v3_ja_calm_male",
        name="落ち着いた男声 (日本語)",
        prefix="jacalmmal",
        language_code="ja-JP",
        language_hint="ja",
        gender=VoiceGender.male,
        description="落ち着いたトーンの男性ナレーターボイス（日本語）。",
    ),
    _OverseasVoiceSpec(
        id="cosyvoice_v3_ja_friendly_female",
        name="親しみやすい女声 (日本語)",
        prefix="jafrnfem",
        language_code="ja-JP",
        language_hint="ja",
        gender=VoiceGender.female,
        description="親しみやすい女性ボイス、ハウツー動画向け（日本語）。",
    ),
    _OverseasVoiceSpec(
        id="cosyvoice_v3_ko_deep_male",
        name="깊이 있는 남성 (한국어)",
        prefix="kodepmal",
        language_code="ko-KR",
        language_hint="ko",
        gender=VoiceGender.male,
        description="신뢰감 있는 깊은 남성 보이스 (한국어).",
    ),
    _OverseasVoiceSpec(
        id="cosyvoice_v3_ko_soft_female",
        name="부드러운 여성 (한국어)",
        prefix="kosoftfem",
        language_code="ko-KR",
        language_hint="ko",
        gender=VoiceGender.female,
        description="부드러운 여성 보이스, 라이프스타일 영상에 적합 (한국어).",
    ),
]
"""6 条海外音色 spec（en/ja/ko × male/female 各 1）。

与 ``_BUILTIN`` 的差异：
    - 不会被 ``bootstrap_builtin_voice_packs`` 自动 seed；
    - 由 ``backend/scripts/seed_overseas_voice_packs.py`` 走
      voice_clone_service 同管线创建后落库；
    - target_model 锁死 ``cosyvoice-v3-plus``，region 锁死 ``ap-singapore``，
      避免被错误派到只支持北京的 v3.5-plus。
"""


__all__ = [
    "OVERSEAS_VOICE_SPECS",
    "bootstrap_builtin_voice_packs",
]
