"""音色包只读 service（W20-T0b，P3 W17 配套）。

职责边界（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：
  * 业务逻辑（按语言 / 系统级 / 供应商过滤的 SELECT 编排）
  * 排序约定（``is_system DESC`` + ``sort_order`` + ``name`` 三层稳定排序）

为什么单独拆 ``voice_packs.py`` 而不复用 ``pattern_library.py``：
    Pattern library 服务聚合的是 P2 钩子工作流的三类 *pattern* 注册表
    （HookPattern / CtaPattern / BrandArchetype），与 P3 W17 的 *voice
    pack* 在领域模型与生命周期上没有直接耦合（VoicePack 还可能由用户
    上传 voice clone 而非全部 system seed）。独立成一个 service 让后续
    扩展 voice clone 上传 / TTS dispatcher 路由时不必回头拆分共享类。

只读语义：
    本模块只暴露列表查询，不开放 Create/Update/Delete；系统级写入路径
    由 :func:`app.services.studio.builtin_voice_packs.bootstrap_builtin_voice_packs`
    在启动期幂等管理。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice_pack import VoicePack


async def list_voice_packs(
    db: AsyncSession,
    *,
    language_code: str | None = None,
    is_system: bool | None = None,
    provider: str | None = None,
) -> list[VoicePack]:
    """按可选条件列出 ``voice_packs`` 表中的全部记录。

    Args:
        db: 当前请求绑定的 ``AsyncSession``，由路由层
            ``Depends(get_db)`` 注入。
        language_code: 可选，按语言代码精确过滤（如 ``"zh-CN"`` /
            ``"en-US"``）；为 ``None`` 时不参与过滤。
        is_system: 可选，``True`` 仅列系统级 seed，``False`` 仅列用户
            自定义；为 ``None`` 时返回全部。
        provider: 可选，按 TTS 供应商精确过滤（如
            ``"aliyun_cosyvoice"`` / ``"openai_tts"``）；为 ``None`` 时
            不参与过滤。

    Returns:
        ``list[VoicePack]`` ORM 行；按 ``is_system DESC`` →
        ``sort_order ASC`` → ``name ASC`` 三层稳定排序，确保系统音色
        永远靠前显示，同档位之间按运营预设顺序展示，相同 sort_order
        再以 name 兜底，避免前端选择器抖动。

    关键内部逻辑：
        三个过滤条件互相独立、AND 关系组合；空字符串视作有效字符串
        过滤值（不会自动当成 ``None`` 跳过），由调用方保证传 ``None``
        而非空串以表达"不过滤"。
    """

    stmt = select(VoicePack)
    if language_code is not None:
        stmt = stmt.where(VoicePack.language_code == language_code)
    if is_system is not None:
        stmt = stmt.where(VoicePack.is_system == is_system)
    if provider is not None:
        stmt = stmt.where(VoicePack.provider == provider)
    stmt = stmt.order_by(
        VoicePack.is_system.desc(),
        VoicePack.sort_order.asc(),
        VoicePack.name.asc(),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


__all__ = ["list_voice_packs"]
