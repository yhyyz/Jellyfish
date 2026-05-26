"""ShotProductReferenceResolver 单测（W16 T16-5 Decision H）。

覆盖：
1. focus_level=none → 返回空列表 + 1 条 warning。
2. focus_level=hero → FRONT/THREE_QUARTER/DETAIL 顺序。
3. focus_level=functional → DETAIL/THREE_QUARTER/FRONT 顺序。
4. focus_level=subtle → THREE_QUARTER/FRONT 顺序（仅 2）。
5. shot-grain link 优先于 project-grain（最特定胜出）。
6. project-grain link 在缺乏更高粒度时被使用。
7. shot-grain + project-grain 同时存在时不混用，仅取 shot-grain。
8. 多 product 总图超 max_total（=9）时尾部被裁剪并发出 warning。
9. focus_level_override 覆盖 DB 上 product_focus_level=none 的行为。
"""

from __future__ import annotations

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
from app.services.studio.generation.video.shot_product_reference_resolver import (
    PRIORITY_BY_FOCUS_LEVEL,
    ShotProductReferenceResolver,
)


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """构造一个一次性的内存 sqlite AsyncSession 与 engine。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_project_chapter_shot(
    db: AsyncSession,
    *,
    focus_level: ProductFocusLevel = ProductFocusLevel.none,
    shot_id: str = "shot-1",
    chapter_id: str = "ch-1",
    project_id: str = "proj-1",
) -> tuple[str, str, str]:
    """种入最小可行的 project / chapter / shot / shot_detail 链路。"""
    project = Project(
        id=project_id,
        name=f"项目-{project_id}",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    chapter = Chapter(id=chapter_id, project_id=project_id, index=1, title="第一章")
    shot = Shot(
        id=shot_id,
        chapter_id=chapter_id,
        index=1,
        title="镜头",
        script_excerpt="角色推门而入。",
        product_focus_level=focus_level,
    )
    detail = ShotDetail(
        id=shot_id,
        camera_shot=CameraShotType.ms,
        angle=CameraAngle.eye_level,
        movement=CameraMovement.static,
        duration=4,
        vfx_type=VFXType.none,
        description="",
    )
    db.add_all([project, chapter, shot, detail])
    await db.commit()
    return project_id, chapter_id, shot_id


async def _add_file(db: AsyncSession, file_id: str) -> None:
    db.add(
        FileItem(
            id=file_id,
            type=FileType.image,
            name=f"{file_id}.png",
            storage_key=f"k/{file_id}",
        )
    )


async def _add_product_with_images(
    db: AsyncSession,
    *,
    product_id: str,
    angle_to_file_id: dict[AssetViewAngle, str],
) -> None:
    """新增一个 product 并按 view_angle 挂上对应 ProductImage。"""
    db.add(
        Product(
            id=product_id,
            name=f"商品-{product_id}",
            description="",
        )
    )
    for angle, file_id in angle_to_file_id.items():
        await _add_file(db, file_id)
        db.add(
            ProductImage(
                product_id=product_id,
                file_id=file_id,
                quality_level=AssetQualityLevel.low,
                view_angle=angle,
            )
        )
    await db.flush()


async def _link_product(
    db: AsyncSession,
    *,
    project_id: str,
    product_id: str,
    chapter_id: str | None = None,
    shot_id: str | None = None,
) -> None:
    db.add(
        ProjectProductLink(
            project_id=project_id,
            product_id=product_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
        )
    )
    await db.flush()


def test_priority_table_matches_decision_h() -> None:
    """PRIORITY_BY_FOCUS_LEVEL 必须严格对齐 Decision H 序列。"""
    assert PRIORITY_BY_FOCUS_LEVEL[ProductFocusLevel.hero] == (
        AssetViewAngle.front,
        AssetViewAngle.three_quarter,
        AssetViewAngle.detail,
    )
    assert PRIORITY_BY_FOCUS_LEVEL[ProductFocusLevel.functional] == (
        AssetViewAngle.detail,
        AssetViewAngle.three_quarter,
        AssetViewAngle.front,
    )
    assert PRIORITY_BY_FOCUS_LEVEL[ProductFocusLevel.subtle] == (
        AssetViewAngle.three_quarter,
        AssetViewAngle.front,
    )
    assert PRIORITY_BY_FOCUS_LEVEL[ProductFocusLevel.none] == ()


@pytest.mark.asyncio
async def test_resolve_returns_empty_when_focus_level_none() -> None:
    """focus_level=none 不解析参考图，返回 ([], 1 条警告)。"""
    db, engine = await _build_session()
    async with db:
        _ = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.none)
        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id="shot-1")
        assert file_ids == []
        assert len(warnings) == 1
        assert "none" in warnings[0]
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_hero_uses_front_three_quarter_detail_order() -> None:
    """hero 序列：FRONT → THREE_QUARTER → DETAIL。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.hero)
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.front: "f-front",
                AssetViewAngle.three_quarter: "f-tq",
                AssetViewAngle.detail: "f-detail",
            },
        )
        await _link_product(db, project_id=project_id, product_id="prod-1")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id=shot_id)
        assert file_ids == ["f-front", "f-tq", "f-detail"]
        assert warnings == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_functional_uses_detail_three_quarter_front_order() -> None:
    """functional 序列：DETAIL → THREE_QUARTER → FRONT。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.functional)
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.front: "f-front",
                AssetViewAngle.three_quarter: "f-tq",
                AssetViewAngle.detail: "f-detail",
            },
        )
        await _link_product(db, project_id=project_id, product_id="prod-1")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id=shot_id)
        assert file_ids == ["f-detail", "f-tq", "f-front"]
        assert warnings == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_subtle_uses_two_angle_priority_only() -> None:
    """subtle 序列：仅 THREE_QUARTER → FRONT，且不含 DETAIL。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.subtle)
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.front: "f-front",
                AssetViewAngle.three_quarter: "f-tq",
                AssetViewAngle.detail: "f-detail",
            },
        )
        await _link_product(db, project_id=project_id, product_id="prod-1")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id=shot_id)
        assert file_ids == ["f-tq", "f-front"]
        assert "f-detail" not in file_ids
        assert warnings == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_prefers_shot_grain_link_over_project_grain() -> None:
    """同时存在 shot-grain 与 project-grain 时，只取 shot-grain。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.hero)
        # shot-grain 商品
        await _add_product_with_images(
            db,
            product_id="prod-shot",
            angle_to_file_id={AssetViewAngle.front: "f-shot-front"},
        )
        await _link_product(
            db,
            project_id=project_id,
            product_id="prod-shot",
            shot_id=shot_id,
        )
        # project-grain 商品
        await _add_product_with_images(
            db,
            product_id="prod-proj",
            angle_to_file_id={AssetViewAngle.front: "f-proj-front"},
        )
        await _link_product(db, project_id=project_id, product_id="prod-proj")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, _ = await resolver.resolve(db, shot_id=shot_id)
        assert file_ids == ["f-shot-front"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_falls_back_to_project_grain_when_no_specific_link() -> None:
    """无 shot/chapter 级关联时，使用 project-grain。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.hero)
        await _add_product_with_images(
            db,
            product_id="prod-proj",
            angle_to_file_id={AssetViewAngle.front: "f-proj-front"},
        )
        await _link_product(db, project_id=project_id, product_id="prod-proj")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, _ = await resolver.resolve(db, shot_id=shot_id)
        assert file_ids == ["f-proj-front"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_returns_empty_when_no_links_found() -> None:
    """有 focus_level 但无任何关联商品时返回空 + warning。"""
    db, engine = await _build_session()
    async with db:
        _ = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.hero)
        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id="shot-1")
        assert file_ids == []
        assert any("商品" in msg or "product" in msg.lower() for msg in warnings)
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_caps_total_at_max_total_with_warning() -> None:
    """4 个 product × 3 张 = 12 张总图超过 max_total=9 时尾部裁剪并 warning。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.hero)
        for i in range(4):
            pid = f"prod-{i}"
            await _add_product_with_images(
                db,
                product_id=pid,
                angle_to_file_id={
                    AssetViewAngle.front: f"f{i}-front",
                    AssetViewAngle.three_quarter: f"f{i}-tq",
                    AssetViewAngle.detail: f"f{i}-detail",
                },
            )
            await _link_product(db, project_id=project_id, product_id=pid)
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, warnings = await resolver.resolve(db, shot_id=shot_id, max_total=9)
        assert len(file_ids) == 9
        assert any(
            "overflow" in msg.lower() or "9" in msg or "drop" in msg.lower()
            for msg in warnings
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_focus_level_override_takes_precedence_over_db() -> None:
    """focus_level_override=hero 应覆盖 DB 中 none 的设置。"""
    db, engine = await _build_session()
    async with db:
        project_id, _, shot_id = await _seed_project_chapter_shot(db, focus_level=ProductFocusLevel.none)
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={AssetViewAngle.front: "f-front"},
        )
        await _link_product(db, project_id=project_id, product_id="prod-1")
        await db.commit()

        resolver = ShotProductReferenceResolver()
        file_ids, _ = await resolver.resolve(
            db,
            shot_id=shot_id,
            focus_level_override=ProductFocusLevel.hero,
        )
        assert file_ids == ["f-front"]
    await engine.dispose()
