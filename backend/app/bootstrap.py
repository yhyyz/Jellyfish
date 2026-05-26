"""应用级注册入口：统一初始化供应商能力 / 任务执行器 / 系统级数据。

启动顺序由 ``app.main.lifespan`` 调度：
1. ``bootstrap_all_registries()``       —— 进程内同步注册（内存数据结构）；
2. ``bootstrap_async_state(db)``         —— 需要数据库会话的异步引导
   （提示词、合规规则集等）。

异步引导的子步骤顺序固定为 ``prompts -> formulas -> compliance``，
理由：
- prompts 不依赖任何业务表；
- formulas（W3-T2）可能引用 prompts；
- compliance 与 prompts/formulas 互不耦合，但放在最后避免阻塞前两步。

所有步骤均为幂等，可在测试 / Celery worker 启动时重复调用。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


def bootstrap_all_registries() -> None:
    """启动时或惰性路径中调用一次即可；顺序固定为 provider 先于 task adapter。"""
    from app.core.tasks.bootstrap import bootstrap_task_adapters
    from app.services.llm.provider_bootstrap import bootstrap_builtin_providers

    bootstrap_builtin_providers()
    bootstrap_task_adapters()


async def bootstrap_async_state(db: AsyncSession) -> dict[str, dict[str, int]]:
    """需要 DB 会话的启动初始化：写入所有系统级 seed 数据。

    - 在 FastAPI ``lifespan`` 中、表结构创建之后调用；
    - 幂等：重复调用只会把 DB 内容"纠回"到 canonical 版本；
    - 顺序合同：``story_formulas.prompt_template_id`` 上有
      ``ON DELETE RESTRICT`` 外键指向 ``prompt_templates``，因此
      ``prompts`` 必须先于 ``formulas``；``compliance`` 与前两者无依赖；
      ``hook_patterns`` / ``cta_patterns`` / ``brand_archetypes`` 三个 P2
      模式库与上述任一 seed 均无外键依赖，按"语义相关度"附在 commerce
      已有 seed 后面，便于启动日志统一检视；
    - 返回各子 bootstrap 的统计字典，便于启动日志打印与启动期断言：

        {
            "prompts":          {"inserted": N, "updated": M, "unchanged": K},
            "formulas":         {"inserted": N, "updated": M, "unchanged": K},
            "compliance":       {"inserted": N, "updated": M, "unchanged": K},
            "hook_patterns":    {"inserted": N, "updated": M, "unchanged": K},
            "cta_patterns":     {"inserted": N, "updated": M, "unchanged": K},
            "brand_archetypes": {"inserted": N, "updated": M, "unchanged": K},
        }
    """

    from app.services.commerce.builtin_brand_archetypes import (
        bootstrap_builtin_brand_archetypes,
    )
    from app.services.commerce.builtin_cta_patterns import (
        bootstrap_builtin_cta_patterns,
    )
    from app.services.commerce.builtin_hook_patterns import (
        bootstrap_builtin_hook_patterns,
    )
    from app.services.commerce.builtin_story_formulas import (
        bootstrap_builtin_story_formulas,
    )
    from app.services.compliance.bootstrap_compliance import (
        bootstrap_builtin_compliance_profiles,
    )
    from app.services.studio.builtin_prompts import bootstrap_builtin_prompts
    from app.services.studio.builtin_subtitle_styles import (
        bootstrap_builtin_subtitle_styles,
    )
    from app.services.studio.builtin_voice_packs import bootstrap_builtin_voice_packs

    stats: dict[str, dict[str, int]] = {}
    stats["prompts"] = await bootstrap_builtin_prompts(db)
    stats["formulas"] = await bootstrap_builtin_story_formulas(db)
    stats["compliance"] = await bootstrap_builtin_compliance_profiles(db)
    stats["hook_patterns"] = await bootstrap_builtin_hook_patterns(db)
    stats["cta_patterns"] = await bootstrap_builtin_cta_patterns(db)
    stats["brand_archetypes"] = await bootstrap_builtin_brand_archetypes(db)
    stats["voice_packs"] = await bootstrap_builtin_voice_packs(db)
    stats["subtitle_styles"] = await bootstrap_builtin_subtitle_styles(db)
    return stats
