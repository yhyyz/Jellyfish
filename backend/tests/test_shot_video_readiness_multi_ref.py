"""shot_video_readiness multi_ref 模式测试（W16 T16-5 Decision H）。

覆盖：
1. multi_ref + focus_level=none → 不就绪，原因提示 product_focus_level 为 none。
2. multi_ref + focus_level=hero + 无关联商品 → 不就绪，原因提示未关联商品。
3. multi_ref + focus_level=hero + 1 个商品有 FRONT 图 → 准备度通过。
4. multi_ref + focus_level=hero + 1 个商品无任何图 → 不就绪。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base
from app.models.commerce_assets import (
    Product,
    ProductImage,
    ProjectProductLink,
)
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.models.studio import (
    AssetQualityLevel,
    AssetViewAngle,
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Chapter,
    FileItem,
    FileType,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotDetail,
    VFXType,
)
from app.models.types import ProductFocusLevel
from app.services.studio.shot_video_readiness import get_shot_video_readiness


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_minimal_graph(
    db: AsyncSession,
    *,
    focus_level: ProductFocusLevel,
) -> None:
    project = Project(
        id="p1",
        name="项目",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    chapter = Chapter(id="c1", project_id="p1", index=1, title="第一章")
    shot = Shot(
        id="s1",
        chapter_id="c1",
        index=1,
        title="镜头",
        script_excerpt="角色推门而入。",
        last_extracted_at=datetime.now(timezone.utc),
        product_focus_level=focus_level,
    )
    detail = ShotDetail(
        id="s1",
        camera_shot=CameraShotType.ms,
        angle=CameraAngle.eye_level,
        movement=CameraMovement.static,
        duration=4,
        vfx_type=VFXType.none,
        description="",
    )
    provider = Provider(
        id="prov1",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="k",
    )
    model = Model(
        id="m_video",
        name="happyhorse-1.0-r2v",
        category=ModelCategoryKey.video,
        provider_id="prov1",
    )
    settings = ModelSettings(id=1, default_video_model_id="m_video")
    db.add_all([project, chapter, shot, detail, provider, model, settings])
    await db.commit()


@pytest.mark.asyncio
async def test_multi_ref_not_ready_when_focus_level_is_none() -> None:
    """focus_level=none 时 multi_ref 必然不就绪，原因提示 none。"""
    db, engine = await _build_session()
    async with db:
        await _seed_minimal_graph(db, focus_level=ProductFocusLevel.none)
        readiness = await get_shot_video_readiness(
            db, shot_id="s1", reference_mode="multi_ref"
        )
        checks = {item.key: item for item in readiness.checks}
        assert readiness.ready is False
        assert checks["reference_frames_ready"].ok is False
        assert "none" in checks["reference_frames_ready"].message
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_not_ready_without_linked_products() -> None:
    """focus_level=hero 但无任何 ProjectProductLink 时不就绪。"""
    db, engine = await _build_session()
    async with db:
        await _seed_minimal_graph(db, focus_level=ProductFocusLevel.hero)
        readiness = await get_shot_video_readiness(
            db, shot_id="s1", reference_mode="multi_ref"
        )
        checks = {item.key: item for item in readiness.checks}
        assert readiness.ready is False
        assert checks["reference_frames_ready"].ok is False
        assert (
            "未关联" in checks["reference_frames_ready"].message
            or "无可用" in checks["reference_frames_ready"].message
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_ready_when_hero_has_one_front_product_image() -> None:
    """focus_level=hero + 1 个商品 + 1 张 FRONT 图 → 参考帧就绪。"""
    db, engine = await _build_session()
    async with db:
        await _seed_minimal_graph(db, focus_level=ProductFocusLevel.hero)
        db.add(FileItem(
            id="ff",
            type=FileType.image,
            name="ff.png",
            storage_key="k/ff",
        ))
        db.add(Product(id="prod-1", name="商品-1", description=""))
        await db.flush()
        db.add(
            ProductImage(
                product_id="prod-1",
                file_id="ff",
                quality_level=AssetQualityLevel.low,
                view_angle=AssetViewAngle.front,
            )
        )
        db.add(ProjectProductLink(project_id="p1", product_id="prod-1"))
        await db.commit()

        readiness = await get_shot_video_readiness(
            db, shot_id="s1", reference_mode="multi_ref"
        )
        checks = {item.key: item for item in readiness.checks}
        assert checks["reference_frames_ready"].ok is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_not_ready_when_product_has_no_images() -> None:
    """focus_level=hero + 商品已挂但无任何图片 → 不就绪。"""
    db, engine = await _build_session()
    async with db:
        await _seed_minimal_graph(db, focus_level=ProductFocusLevel.hero)
        db.add(Product(id="prod-1", name="商品-1", description=""))
        await db.flush()
        db.add(ProjectProductLink(project_id="p1", product_id="prod-1"))
        await db.commit()

        readiness = await get_shot_video_readiness(
            db, shot_id="s1", reference_mode="multi_ref"
        )
        checks = {item.key: item for item in readiness.checks}
        assert readiness.ready is False
        assert checks["reference_frames_ready"].ok is False
        assert "图" in checks["reference_frames_ready"].message
    await engine.dispose()
