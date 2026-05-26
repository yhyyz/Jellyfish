"""multi_ref 模式下 ``build_run_args`` 的行为契约（W16 T16-9）。

覆盖目标：
- multi_ref + 调用方显式传入 file_ids → 直接走"手动覆盖"路径，不再触发 resolver。
- multi_ref + 空 images → 自动调用 ``ShotProductReferenceResolver`` 解析商品参考图。
- resolver 解析为空（focus_level=none / 未挂载商品）→ 显式 400，不静默回退到 t2v。
- resolver 返回的 warnings 必须落到 ``run_args["meta"]["reference_warnings"]``，便于任务中心展示。
- multi_ref 走的是 ``reference_images_base64`` 通道，aliyun_bailian 的"补一张关键帧"兜底不应触发。
- 非 multi_ref 模式（first/text_only 等）保持原有 frame_map 行为不变。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.integrations.video_capabilities import VideoModelCapability
from app.models.commerce_assets import (
    Product,
    ProductImage,
    ProjectProductLink,
)
from app.models.llm import (
    Model,
    ModelCategoryKey,
    ModelSettings,
    Provider,
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
    ShotFrameImage,
    ShotFrameType,
    VFXType,
)
from app.models.types import ProductFocusLevel
from app.services.film.generated_video import build_run_args


async def _build_session() -> tuple[AsyncSession, Any]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_shot_graph(
    db: AsyncSession,
    *,
    focus_level: ProductFocusLevel = ProductFocusLevel.hero,
) -> None:
    """种入项目/章节/镜头链路 + 默认视频 model 配置。"""
    project = Project(
        id="p1",
        name="项目一",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    chapter = Chapter(id="c1", project_id="p1", index=1, title="第一章")
    shot = Shot(
        id="s1",
        chapter_id="c1",
        index=1,
        title="镜头一",
        script_excerpt="角色推门而入。",
        product_focus_level=focus_level,
    )
    detail = ShotDetail(
        id="s1",
        camera_shot=CameraShotType.ms,
        angle=CameraAngle.eye_level,
        movement=CameraMovement.static,
        duration=5,
        vfx_type=VFXType.none,
        description="角色推门后微微停顿。",
        first_frame_prompt="首帧",
        last_frame_prompt="尾帧",
        key_frame_prompt="关键帧",
    )
    db.add_all([project, chapter, shot, detail])
    await db.flush()


async def _seed_default_video_model(
    db: AsyncSession,
    *,
    provider_name: str = "OpenAI",
    provider_base_url: str = "https://api.openai.com/v1",
    model_name: str = "happyhorse-1.0-r2v",
) -> None:
    provider = Provider(
        id="prv-1",
        name=provider_name,
        base_url=provider_base_url,
        api_key="k-test",
    )
    model = Model(
        id="m_video",
        name=model_name,
        category=ModelCategoryKey.video,
        provider_id="prv-1",
    )
    settings = ModelSettings(id=1, default_video_model_id="m_video")
    db.add_all([provider, model, settings])
    await db.flush()


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


def _patch_file_id_to_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_db: AsyncSession, *, file_id: str) -> str:
        return f"data:image/png;base64,FILE_{file_id}"

    monkeypatch.setattr(
        "app.services.film.generated_video.file_id_to_data_url",
        _fake,
    )


def _patch_capability_with_max_refs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_reference_images: int = 9,
) -> None:
    """覆写 resolve_video_capability，避免依赖真实模型注册。"""

    cap = VideoModelCapability(
        max_reference_images=max_reference_images,
        supports_r2v=max_reference_images > 0,
        supported_reference_modes=("multi_ref", "text_only"),
    )

    def _fake_resolve(*, provider: str, model: str | None) -> VideoModelCapability:  # noqa: ARG001
        return cap

    monkeypatch.setattr(
        "app.services.film.generated_video.resolve_video_capability",
        _fake_resolve,
        raising=False,
    )


@pytest.mark.asyncio
async def test_multi_ref_with_caller_supplied_images(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式传入 3 个 file_id 时直接使用，无需 resolver。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.none)
        await _seed_default_video_model(db)
        for fid in ("f1", "f2", "f3"):
            await _add_file(db, fid)
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        _patch_capability_with_max_refs(monkeypatch)

        run_args = await build_run_args(
            db,
            shot_id="s1",
            reference_mode="multi_ref",
            prompt="多图参考视频提示词",
            images=["f1", "f2", "f3"],
            ratio="9:16",
        )

        assert run_args["input"]["reference_images_base64"] == [
            "data:image/png;base64,FILE_f1",
            "data:image/png;base64,FILE_f2",
            "data:image/png;base64,FILE_f3",
        ]
        assert run_args["input"]["first_frame_base64"] is None
        assert run_args["input"]["last_frame_base64"] is None
        assert run_args["input"]["key_frame_base64"] is None
        assert run_args["meta"]["reference_mode"] == "multi_ref"
        assert run_args["meta"]["reference_count"] == 3
        # 调用方手动传入时不应该触发 resolver；warnings 默认空。
        assert run_args["meta"]["reference_warnings"] == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_auto_bind_via_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """images 为空时自动调用 resolver，按 hero 优先级序列拉取商品参考图。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.hero)
        await _seed_default_video_model(db)
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.front: "pf-front",
                AssetViewAngle.three_quarter: "pf-tq",
                AssetViewAngle.detail: "pf-detail",
            },
        )
        db.add(
            ProjectProductLink(
                project_id="p1",
                product_id="prod-1",
            )
        )
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        _patch_capability_with_max_refs(monkeypatch)

        run_args = await build_run_args(
            db,
            shot_id="s1",
            reference_mode="multi_ref",
            prompt="多图参考视频提示词",
            images=[],
            ratio="9:16",
        )

        # hero 优先级序列：FRONT → THREE_QUARTER → DETAIL
        assert run_args["input"]["reference_images_base64"] == [
            "data:image/png;base64,FILE_pf-front",
            "data:image/png;base64,FILE_pf-tq",
            "data:image/png;base64,FILE_pf-detail",
        ]
        assert run_args["input"]["first_frame_base64"] is None
        assert run_args["input"]["last_frame_base64"] is None
        assert run_args["input"]["key_frame_base64"] is None
        assert run_args["meta"]["reference_count"] == 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_resolver_empty_raises_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """focus_level=none + 空 images → 显式 400，不静默回退。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.none)
        await _seed_default_video_model(db)
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        _patch_capability_with_max_refs(monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            await build_run_args(
                db,
                shot_id="s1",
                reference_mode="multi_ref",
                prompt="提示词",
                images=[],
                ratio="9:16",
            )

        assert exc_info.value.status_code == 400
        assert "multi_ref" in str(exc_info.value.detail)
        assert "无可用参考图" in str(exc_info.value.detail)
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_warnings_persisted_in_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolver 产生的 warnings 必须出现在 run_args.meta.reference_warnings。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.subtle)
        await _seed_default_video_model(db)
        # subtle 序列只取 THREE_QUARTER 与 FRONT；只挂一张图，会落入"已关联商品但未找到任何
        # 符合优先级序列的 ProductImage"或类似 warning 路径。这里直接挂 1 张 THREE_QUARTER。
        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.three_quarter: "pf-tq",
            },
        )
        db.add(
            ProjectProductLink(
                project_id="p1",
                product_id="prod-1",
            )
        )
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        # 把 max_reference_images 收紧到 1，以便正常路径下 resolver 不会发出预算 warning，
        # 我们改用"resolver mock"的方式验证 warning 被透传。
        _patch_capability_with_max_refs(monkeypatch, max_reference_images=9)

        # 直接 monkeypatch resolver 返回 (file_ids, warnings) 二元组，断言 warnings 落地。
        from app.services.film import generated_video as gv

        async def _fake_resolve(_self, _db, *, shot_id: str, max_total: int = 9, focus_level_override=None):  # noqa: ARG001
            return ["pf-tq"], ["budget overflow: dropped 2", "焦点级别为 subtle，仅取 2 视角"]

        monkeypatch.setattr(
            gv.ShotProductReferenceResolver,
            "resolve",
            _fake_resolve,
        )

        run_args = await build_run_args(
            db,
            shot_id="s1",
            reference_mode="multi_ref",
            prompt="提示词",
            images=[],
            ratio="9:16",
        )

        assert run_args["input"]["reference_images_base64"] == [
            "data:image/png;base64,FILE_pf-tq",
        ]
        assert run_args["meta"]["reference_warnings"] == [
            "budget overflow: dropped 2",
            "焦点级别为 subtle，仅取 2 视角",
        ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_multi_ref_skips_aliyun_bailian_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=aliyun_bailian + multi_ref：不应触发 _pick_fallback_reference_frame_data_url。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.hero)
        # 显式写 aliyun_bailian provider。
        provider = Provider(
            id="prv-1",
            name="阿里百炼",
            base_url="https://dashscope.aliyuncs.com/api/v1",
            api_key="k-aliyun",
        )
        model = Model(
            id="m_video",
            name="happyhorse-1.0-r2v",
            category=ModelCategoryKey.video,
            provider_id="prv-1",
        )
        settings = ModelSettings(id=1, default_video_model_id="m_video")
        db.add_all([provider, model, settings])

        await _add_product_with_images(
            db,
            product_id="prod-1",
            angle_to_file_id={
                AssetViewAngle.front: "pf-front",
            },
        )
        db.add(
            ProjectProductLink(
                project_id="p1",
                product_id="prod-1",
            )
        )
        # 同时挂一张关键帧图，用于证明 fallback 没被使用（如果误用，key_frame_b64 会被填充）。
        db.add(
            ShotFrameImage(
                shot_detail_id="s1",
                frame_type=ShotFrameType.key,
                file_id="kf-1",
                format="png",
            )
        )
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        _patch_capability_with_max_refs(monkeypatch)

        called: dict[str, int] = {"count": 0}

        async def _spy_pick_fallback(_db: AsyncSession, *, shot_id: str) -> str | None:  # noqa: ARG001
            called["count"] += 1
            return f"data:image/png;base64,FALLBACK_{shot_id}"

        monkeypatch.setattr(
            "app.services.film.generated_video._pick_fallback_reference_frame_data_url",
            _spy_pick_fallback,
        )

        run_args = await build_run_args(
            db,
            shot_id="s1",
            reference_mode="multi_ref",
            prompt="提示词",
            images=[],
            ratio="9:16",
        )

        # 关键断言：fallback 没被调用 + 帧槽全空 + multi_ref 通道写入了 reference_images_base64。
        assert called["count"] == 0
        assert run_args["input"]["key_frame_base64"] is None
        assert run_args["input"]["first_frame_base64"] is None
        assert run_args["input"]["last_frame_base64"] is None
        assert run_args["input"]["reference_images_base64"] == [
            "data:image/png;base64,FILE_pf-front",
        ]
        assert run_args["provider"] == "aliyun_bailian"
    await engine.dispose()


@pytest.mark.asyncio
async def test_non_multi_ref_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 multi_ref 模式（first）保持原行为：frame_map 走第一帧；不应出现 reference_images_base64。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db, focus_level=ProductFocusLevel.none)
        await _seed_default_video_model(db, model_name="sora-mini")
        await db.commit()

        _patch_file_id_to_data_url(monkeypatch)
        _patch_capability_with_max_refs(monkeypatch)

        run_args = await build_run_args(
            db,
            shot_id="s1",
            reference_mode="first",
            prompt="提示词",
            images=["frame-first-file"],
            ratio="9:16",
        )

        assert run_args["input"]["first_frame_base64"] == "data:image/png;base64,FILE_frame-first-file"
        assert run_args["input"]["last_frame_base64"] is None
        assert run_args["input"]["key_frame_base64"] is None
        # 非 multi_ref 不应注入 reference_images_base64（None 或不存在均可接受）。
        assert run_args["input"].get("reference_images_base64") in (None, [])
        # meta 字段对非 multi_ref 模式不强制存在；如果存在也不应有 multi_ref 标记。
        if "meta" in run_args:
            assert run_args["meta"].get("reference_mode") != "multi_ref"
    await engine.dispose()
