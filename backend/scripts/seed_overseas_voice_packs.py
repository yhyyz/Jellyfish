#!/usr/bin/env python3
"""W29-T10：通过 voice_clone_service 同管线 seed 6 条海外音色。

为什么存在
----------

W17 的 ``builtin_voice_packs.bootstrap_builtin_voice_packs`` 只 seed 6 条
zh-CN cosyvoice 音色；W28 起前端已支持 ja-JP / ko-KR 整树 + en-US 海外档，
但缺乏对应的"系统级海外音色"可供 VoicePackPicker 选择。

W29 的策略：**不直接往 voice_packs 表里塞硬编码 voice_id**——任何系统级
voice clone 都必须走与用户上传完全相同的 pipeline（DashScope create_voice
→ 异步轮询 → query_voice 直至 OK），让 ``provider_voice_id`` 真实来自
DashScope 平台、未来下线 / 重训也能复用同一管线。

做什么
------

- 6 条海外音色 spec：
  - en-US × 2：``en_warm_male`` / ``en_bright_female``
  - ja-JP × 2：``ja_calm_male`` / ``ja_friendly_female``
  - ko-KR × 2：``ko_deep_male`` / ``ko_soft_female``
  - 全部 ``cosyvoice-v3-plus`` + ``ap-singapore``
- 调用 ``voice_clone_service.create_voice_remote`` 同管线创建
- 完成后 ``persist_voice_pack`` 风格写入 VoicePack 行，但显式标
  ``is_system=True`` + ``clone_status=ready``（由本脚本同步轮询直至 OK
  才落库；区别于 HTTP 路径的"先入库 deploying 再 worker 轮询"）。
- 幂等：以 ``id`` 精确匹配，已存在 spec 则跳过 DashScope 调用。
- ``--dry-run`` 仅 print 计划，不调 DashScope / 不写 DB。

调用方式
--------

::

    # dry-run（不发请求）
    uv run python scripts/seed_overseas_voice_packs.py --dry-run

    # 真实 seed（需要 ap-singapore 区域 DashScope API key）
    uv run python scripts/seed_overseas_voice_packs.py \\
        --sample-url https://your-oss-public/sample.wav

退出码
------

- ``0``：seed 成功（或 ``--dry-run`` 模式）
- ``1``：seed 过程中至少 1 条失败（轮询超时 / DashScope 错误 / DB 异常）
- ``2``：参数校验失败
"""

# pylint: disable=invalid-name,too-many-locals,too-many-statements,too-many-branches

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from typing import Final

from app.core.db import async_session_maker
from app.models.types import (
    VoiceCloneStatus,
    VoiceGender,
    VoiceProvider,
    VoiceRegion,
)
from app.models.voice_pack import VoicePack
from app.services.studio.voice_clone_service import (
    create_voice_remote,
    query_clone_status,
    utcnow_naive,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OverseasVoiceSpec:
    """海外音色 spec（不可变）。

    Attributes:
        id: VoicePack 行主键；命名约定 ``cosyvoice_v3_<lang>_<archetype>``。
        name: UI 展示名称（多语言）。
        prefix: DashScope create_voice 用的 ≤10 字符 slug。
        language_code: 与 ``VoicePack.language_code`` 一致（``en-US`` 等）。
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
"""6 条海外音色 spec 注册表（按 lang × gender 各 1，组合覆盖 en/ja/ko 主流场景）。"""


_OVERSEAS_TARGET_MODEL: Final[str] = "cosyvoice-v3-plus"
"""海外档默认目标模型：v3-plus 同时支持北京 + 新加坡两区，海外档统一新加坡。"""

_OVERSEAS_REGION: Final[VoiceRegion] = VoiceRegion.ap_singapore
"""海外档默认区域：新加坡端点，避开合规风险。"""


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造 argparse parser。"""
    parser = argparse.ArgumentParser(
        description="W29-T10 seed 6 条海外音色（en/ja/ko × 2）走 voice_clone_service 同管线",
    )
    parser.add_argument(
        "--sample-url",
        type=str,
        default="https://dashscope-public.oss-cn-beijing.aliyuncs.com/voice/example_voice_zh.wav",
        help="公网可访问的 voice sample URL；DashScope 会从该 URL 下载训练样本",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印 seed 计划，不调 DashScope / 不写 DB",
    )
    parser.add_argument(
        "--max-poll-attempts",
        type=int,
        default=30,
        help="单条音色轮询最大次数；与 W29-T5 worker MAX_ATTEMPTS 一致",
    )
    parser.add_argument(
        "--poll-interval-sec",
        type=float,
        default=10.0,
        help="单条音色轮询间隔秒数；与 W29-T5 worker POLL_INTERVAL_SEC 一致",
    )
    return parser


async def _seed_one_spec(
    spec: _OverseasVoiceSpec,
    *,
    sample_url: str,
    dry_run: bool,
    max_attempts: int,
    poll_interval: float,
) -> tuple[str, str | None]:
    """seed 单条 spec，返回 ``(status, voice_id_or_reason)``。

    Returns:
        - ``("skipped", existing_id)`` —— 已存在，跳过
        - ``("dry-run", None)`` —— dry-run 模式
        - ``("ok", voice_id)`` —— 创建并轮询到 OK 后落库
        - ``("failed", reason)`` —— 创建或轮询失败
    """

    async with async_session_maker() as session:
        existing = await session.get(VoicePack, spec.id)
        if existing is not None:
            logger.info("skip existing voice pack id=%s", spec.id)
            return "skipped", existing.id

    if dry_run:
        logger.info(
            "[dry-run] would create voice id=%s lang=%s prefix=%s",
            spec.id,
            spec.language_code,
            spec.prefix,
        )
        return "dry-run", None

    try:
        voice_id = await create_voice_remote(
            target_model=_OVERSEAS_TARGET_MODEL,
            prefix=spec.prefix,
            sample_url=sample_url,
            region=_OVERSEAS_REGION,
            language_hints=[spec.language_hint],
        )
    except Exception as exc:  # noqa: BLE001 - SDK 抛多种异常
        logger.error("create_voice failed for spec=%s: %s", spec.id, exc)
        return "failed", f"create_voice error: {exc}"

    deadline_attempts = 0
    while deadline_attempts < max_attempts:
        status, reason = await query_clone_status(
            voice_id=voice_id, region=_OVERSEAS_REGION
        )
        if status == VoiceCloneStatus.ready:
            break
        if status == VoiceCloneStatus.failed:
            return "failed", reason or "DashScope returned failed"
        deadline_attempts += 1
        await asyncio.sleep(poll_interval)
    else:
        return "failed", "polling timed out"

    async with async_session_maker() as session:
        record = VoicePack(
            id=spec.id,
            name=spec.name,
            provider=VoiceProvider.aliyun_cosyvoice,
            provider_voice_id=voice_id,
            language_code=spec.language_code,
            gender=spec.gender,
            archetype_hint=None,
            description=spec.description,
            default_speed=1.0,
            is_system=True,
            sort_order=100,
            target_model=_OVERSEAS_TARGET_MODEL,
            region=_OVERSEAS_REGION,
            clone_status=VoiceCloneStatus.ready,
            sample_audio_oss_key=None,
            cloned_at=utcnow_naive(),
        )
        session.add(record)
        await session.commit()
    return "ok", voice_id


async def _run(args: argparse.Namespace) -> int:
    """主流程：依次 seed 6 条海外音色，返回总退出码。"""
    failures: list[tuple[str, str]] = []
    successes: list[tuple[str, str]] = []
    skipped: list[str] = []

    for spec in OVERSEAS_VOICE_SPECS:
        outcome, info = await _seed_one_spec(
            spec,
            sample_url=args.sample_url,
            dry_run=args.dry_run,
            max_attempts=args.max_poll_attempts,
            poll_interval=args.poll_interval_sec,
        )
        if outcome == "skipped":
            skipped.append(spec.id)
        elif outcome == "ok":
            successes.append((spec.id, info or ""))
        elif outcome == "dry-run":
            successes.append((spec.id, "dry-run"))
        else:
            failures.append((spec.id, info or "unknown"))

    print("---- W29 海外音色 seed 结果 ----")
    print(f"successes: {len(successes)}")
    for spec_id, voice_id in successes:
        print(f"  ok  {spec_id} -> {voice_id}")
    print(f"skipped (已存在): {len(skipped)}")
    for spec_id in skipped:
        print(f"  skip {spec_id}")
    print(f"failures: {len(failures)}")
    for spec_id, reason in failures:
        print(f"  FAIL {spec_id} -> {reason}")

    return 1 if failures else 0


def main() -> int:
    """脚本 CLI 入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_arg_parser().parse_args()
    started = time.time()
    rc = asyncio.run(_run(args))
    print(f"elapsed: {time.time() - started:.2f}s rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
