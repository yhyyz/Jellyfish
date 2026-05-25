"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1.routes import film, health, llm, studio
from app.api.v1.routes.commerce import router as commerce_router
from app.api.v1.routes.script import router as script_router
from app.api.v1.routes.studio import story_formulas, story_projects, story_variants

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(film.router, prefix="/film", tags=["film"])
router.include_router(llm.router, prefix="/llm", tags=["llm"])
router.include_router(studio.router, prefix="/studio")
router.include_router(commerce_router, prefix="/commerce")
router.include_router(script_router)

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
