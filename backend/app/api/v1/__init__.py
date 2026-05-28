"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1.routes import film, health, llm, studio
from app.api.v1.routes.commerce import router as commerce_router
from app.api.v1.routes.script import router as script_router
from app.api.v1.routes.settings import router as settings_router
from app.api.v1.routes.studio import (
    brand_archetypes,
    brand_style_guides,
    cta_patterns,
    hook_patterns,
    story_formulas,
    story_projects,
    story_variants,
)

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(film.router, prefix="/film", tags=["film"])
router.include_router(llm.router, prefix="/llm", tags=["llm"])
router.include_router(studio.router, prefix="/studio")
router.include_router(commerce_router, prefix="/commerce")
router.include_router(script_router)

# === P4 W24-T1: settings/api-keys admin（per-key 配额管理）===
# race-aware：放在 commerce/script 之后，确保上游路由聚合先就位，
# 不会因为 import 时序意外覆盖既有 prefix。
router.include_router(settings_router, prefix="/settings")

# === W6-T2: Story-Driven Commerce 入口（独立挂载，避免与 W6-T1/T3 冲突）===
router.include_router(
    story_formulas.router,
    prefix="/studio/story-formulas",
    tags=["studio/story-formulas"],
)
router.include_router(
    story_projects.router,
    prefix="/studio/story-projects",
    tags=["studio/story-projects"],
)
router.include_router(
    story_variants.router,
    prefix="/studio/story-variants",
    tags=["studio/story-variants"],
)

# === W14-T4: Pattern library 只读 API（hook/cta/archetype 选择器）===
router.include_router(
    hook_patterns.router,
    prefix="/studio/hook-patterns",
    tags=["studio/hook-patterns"],
)
router.include_router(
    cta_patterns.router,
    prefix="/studio/cta-patterns",
    tags=["studio/cta-patterns"],
)
router.include_router(
    brand_archetypes.router,
    prefix="/studio/brand-archetypes",
    tags=["studio/brand-archetypes"],
)

# === W25-T3: BrandStyleGuide 1:1 per-Product 子资源 CRUD ===
# 独立挂载于 /studio 前缀下；route 内部已声明
# `/products/{product_id}/brand-style-guide` 完整子路径，
# 不复用 studio.router 的 /products 前缀（race-aware：与 sibling 任务 T25-1 /
# T25-2 并行时避免 router 注册顺序冲突）。
router.include_router(
    brand_style_guides.router,
    prefix="/studio",
    tags=["studio/brand-style-guides"],
)
