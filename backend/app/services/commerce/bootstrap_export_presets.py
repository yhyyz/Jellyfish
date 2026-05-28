"""系统级 :class:`PlatformExportPreset` 内置启动注册（W23-T1，P4 Wave A）。

为什么存在：
    P4 Wave A 引入"多平台导出预设"基础设施，前端 PlatformExportPresetLibrary
    与后端 chapter_av_export 渲染管线（W23-T2）都依赖一份"系统默认可用"
    的内置预设清单。该清单不应依赖人工 SQL，而要随应用启动自动到位（与
    ``builtin_voice_packs`` / ``builtin_subtitle_styles`` 风格保持一致）。

做什么：
    :func:`bootstrap_platform_export_presets` 在应用启动时被调用：

    * 写入 5 个系统预设：
      - ``douyin_default``       — 抖音 9:16 / 60s
      - ``kuaishou_default``     — 快手 9:16 / 57s
      - ``xiaohongshu_default``  — 小红书 1:1 / 60s
      - ``youtube_shorts_default`` — YouTube Shorts 9:16 / 59s
      - ``tiktok_default``       — TikTok 9:16 / 60s
    * 幂等：以主键 ``id`` 定位，不存在则 INSERT，存在但有差异则 UPDATE，
      相同则跳过；
    * 全部标记 ``is_system=True``，业务侧不允许删除（CRUD service 层在
      DELETE 路径直接返回 400 拒绝）；
    * ``sort_order`` 按平台优先级递增（抖音 0 / 快手 10 / 小红书 20 /
      YouTube 30 / TikTok 40），便于前端按"国内优先"分组展示。

幂等性契约：
    SELECT id WHERE id=spec.id
        if exists & 全字段一致 -> "unchanged"
        if exists & 任一字段不同 -> "updated"（覆盖回 spec）
        else -> "inserted"

调用方：``app.bootstrap.bootstrap_async_state``（FastAPI lifespan 内）。

注意：``subtitle_style_id`` / ``voice_pack_id`` 字段在 W23-T1 阶段全部
留空（None），等后续 wave 决定"平台 → 默认字幕样式 / 音色"的映射策略
后再回填，避免现在就把跨表绑定写死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_export_preset import PlatformExportPreset
from app.models.types import Platform


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuiltinPlatformExportPresetSpec:
    """单个内置平台导出预设的不变定义。

    字段含义：
        id: 数据库主键；命名约定 ``<platform>_default``。
        name: UI 展示名（中文短名）。
        platform: :class:`Platform` 枚举值（douyin / kuaishou / ...）。
        aspect_ratio: 画幅比例字符串（``9:16`` / ``1:1`` / ``16:9``）。
        max_duration_sec: 该平台允许的最大单条时长（秒）。
        file_format: 容器格式（``mp4`` / ``mov``）。
        codec_preset: 编码预设字符串。
        loudness_lufs: 目标响度 LUFS（负值）。
        sort_order: UI 排序权重，越小越靠前。
        description: 运营备注。
        sticker_specs: 贴纸装配模板，缺省空数组。
        subtitle_style_id / voice_pack_id / watermark_file_id: P4 Wave A
            阶段统一为 None，等后续 wave 决定默认绑定。
    """

    id: str
    name: str
    platform: Platform
    aspect_ratio: str
    max_duration_sec: int
    file_format: str
    codec_preset: str
    loudness_lufs: float
    sort_order: int
    description: str
    sticker_specs: list[dict[str, Any]] = field(default_factory=list)
    subtitle_style_id: str | None = None
    voice_pack_id: str | None = None
    watermark_file_id: str | None = None


# ---------------------------------------------------------------------------
# 注册表（5 个系统预设，顺序即 sort_order 顺序）
# ---------------------------------------------------------------------------


_BUILTIN: Final[list[_BuiltinPlatformExportPresetSpec]] = [
    _BuiltinPlatformExportPresetSpec(
        id="douyin_default",
        name="抖音默认",
        platform=Platform.douyin,
        aspect_ratio="9:16",
        max_duration_sec=60,
        file_format="mp4",
        codec_preset="h264_high_4_1",
        loudness_lufs=-16.0,
        sort_order=0,
        description="抖音竖屏默认预设：9:16 画幅、60 秒上限、H.264 High 4.1 编码、-16 LUFS",
    ),
    _BuiltinPlatformExportPresetSpec(
        id="kuaishou_default",
        name="快手默认",
        platform=Platform.kuaishou,
        aspect_ratio="9:16",
        max_duration_sec=57,
        file_format="mp4",
        codec_preset="h264_high_4_1",
        loudness_lufs=-16.0,
        sort_order=10,
        description="快手竖屏默认预设：9:16 画幅、57 秒上限（平台口径预留 3 秒余量）",
    ),
    _BuiltinPlatformExportPresetSpec(
        id="xiaohongshu_default",
        name="小红书方屏",
        platform=Platform.xiaohongshu,
        aspect_ratio="1:1",
        max_duration_sec=60,
        file_format="mp4",
        codec_preset="h264_high_4_1",
        loudness_lufs=-16.0,
        sort_order=20,
        description="小红书方屏默认预设：1:1 画幅、60 秒上限、H.264 High 4.1 编码",
    ),
    _BuiltinPlatformExportPresetSpec(
        id="youtube_shorts_default",
        name="YouTube Shorts 默认",
        platform=Platform.youtube,
        aspect_ratio="9:16",
        max_duration_sec=59,
        file_format="mp4",
        codec_preset="h264_high_4_1",
        loudness_lufs=-14.0,
        sort_order=30,
        description="YouTube Shorts 竖屏预设：9:16 画幅、59 秒上限、-14 LUFS（YT 平台标准）",
    ),
    _BuiltinPlatformExportPresetSpec(
        id="tiktok_default",
        name="TikTok 默认",
        platform=Platform.tiktok,
        aspect_ratio="9:16",
        max_duration_sec=60,
        file_format="mp4",
        codec_preset="h264_high_4_1",
        loudness_lufs=-14.0,
        sort_order=40,
        description="TikTok 竖屏默认预设：9:16 画幅、60 秒上限、-14 LUFS（TikTok 推荐响度）",
    ),
]


# ---------------------------------------------------------------------------
# 启动函数
# ---------------------------------------------------------------------------


async def bootstrap_platform_export_presets(
    db: AsyncSession,
) -> dict[str, int]:
    """启动时调用，幂等地确保 5 个系统级平台导出预设存在并保持 canonical。

    幂等策略：
        以主键 ``id`` 查询已有记录：
            * 命中 + 字段全部一致 -> ``unchanged`` 计数；
            * 命中 + 任一字段不同 -> ``updated`` 计数（覆盖回 spec）；
              注意：``is_system`` 视为不变量（始终 True），不会被本函数
              修改；
            * 未命中 -> ``inserted`` 计数（按 spec 新插入）。

    用户自定义预设（``is_system=False``）不在本函数管辖范围内：
        seed 只负责系统行；用户派生的预设生命周期由 CRUD service
        管理。

    Args:
        db: 已绑定到目标库的 :class:`AsyncSession`；本函数只对
            ``platform_export_presets`` 表读 / 写，并在最后一次性
            ``commit()``。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}`` 计数字典，便于
        启动日志直接打印或被测试断言；保持与 ``bootstrap_builtin_voice
        _packs`` / ``bootstrap_builtin_compliance_profiles`` 同形契约。
    """

    inserted = 0
    updated = 0
    unchanged = 0

    for spec in _BUILTIN:
        existing = await db.get(PlatformExportPreset, spec.id)
        if existing is None:
            db.add(
                PlatformExportPreset(
                    id=spec.id,
                    name=spec.name,
                    platform=spec.platform,
                    aspect_ratio=spec.aspect_ratio,
                    max_duration_sec=spec.max_duration_sec,
                    subtitle_style_id=spec.subtitle_style_id,
                    voice_pack_id=spec.voice_pack_id,
                    watermark_file_id=spec.watermark_file_id,
                    sticker_specs=list(spec.sticker_specs),
                    file_format=spec.file_format,
                    codec_preset=spec.codec_preset,
                    loudness_lufs=spec.loudness_lufs,
                    is_system=True,
                    sort_order=spec.sort_order,
                    description=spec.description,
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


def _is_same(
    record: PlatformExportPreset,
    spec: _BuiltinPlatformExportPresetSpec,
) -> bool:
    """比较 DB 行与 spec 是否完全一致；用于决定 unchanged vs updated。

    可变字段：所有展示 / 编码 / 时长 / 响度 / 排序字段；``is_system``
    视为不变量（始终 True），不参与比较。
    """

    return (
        record.name == spec.name
        and _platform_equals(record.platform, spec.platform)
        and record.aspect_ratio == spec.aspect_ratio
        and record.max_duration_sec == spec.max_duration_sec
        and record.subtitle_style_id == spec.subtitle_style_id
        and record.voice_pack_id == spec.voice_pack_id
        and record.watermark_file_id == spec.watermark_file_id
        and list(record.sticker_specs or []) == list(spec.sticker_specs)
        and record.file_format == spec.file_format
        and record.codec_preset == spec.codec_preset
        and float(record.loudness_lufs) == float(spec.loudness_lufs)
        and record.sort_order == spec.sort_order
        and record.description == spec.description
    )


def _apply_spec(
    record: PlatformExportPreset,
    spec: _BuiltinPlatformExportPresetSpec,
) -> None:
    """把 spec 的可变字段同步到一行 ORM 记录上。"""

    record.name = spec.name
    record.platform = spec.platform
    record.aspect_ratio = spec.aspect_ratio
    record.max_duration_sec = spec.max_duration_sec
    record.subtitle_style_id = spec.subtitle_style_id
    record.voice_pack_id = spec.voice_pack_id
    record.watermark_file_id = spec.watermark_file_id
    record.sticker_specs = list(spec.sticker_specs)
    record.file_format = spec.file_format
    record.codec_preset = spec.codec_preset
    record.loudness_lufs = spec.loudness_lufs
    record.sort_order = spec.sort_order
    record.description = spec.description


def _platform_equals(left: object, right: Platform) -> bool:
    """容忍 SQLAlchemy 不同后端对 Enum 列返回的 str / Enum 差异。

    SQLite 把 Enum 列以原始字符串返回，MySQL 在 ``native_enum=True``
    下返回 Enum 实例；统一比较 ``.value`` 即可。
    """

    if isinstance(left, Platform):
        return left == right
    return str(left) == right.value


__all__ = [
    "bootstrap_platform_export_presets",
]
