"""``commerce_export_worker`` 单元测试（W23-T2，P4 Wave B）。

覆盖（≥3 cases）：

1. ``test_executor_registered_with_commerce_export_task_kind``：注册元数据。
2. ``test_executor_timeout_set_to_1800s``：slow 队列超时上限。
3. ``test_runner_rejects_missing_variant_id`` / ``..._preset_id``：入参兜底。
4. ``test_worker_lifecycle_running_to_succeeded``：mock 子进程 + storage，
   验证完整生命周期 + GenerationTask.status 走到 succeeded。
5. ``test_worker_writes_FileItem_with_usage_kind_product_export``：成功路径
   会落 :class:`FileItem` 行 + :class:`FileUsage` 行（``product_export``）。

测试架构：mock ``_run_ffmpeg`` + ``storage.upload_file`` + ``storage.download_file``，
不依赖真实子进程。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.storage import StoredFileInfo
from app.models.platform_export_preset import PlatformExportPreset
from app.models.story_formula import StoryFormula, StoryVariant
from app.models.studio import Chapter, FileItem, FileType, FileUsage, Project
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.studio_projects import ProjectStyle
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import (
    FileUsageKind,
    FormulaRegion,
    Platform,
    PromptCategory,
)
from app.services.commerce import commerce_export_worker as worker_mod
from app.services.commerce.commerce_export_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_commerce_export_executor,
    run_commerce_export_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


_PROJECT_ID = "proj-w23-export"
_CHAPTER_ID = "chap-w23-export"
_VARIANT_ID = "var-w23-export"
_FORMULA_ID = "formula-test"
_PROMPT_TEMPLATE_ID = "prompt-template-test"
_PRESET_ID = "preset-douyin-test"
_MASTER_FILE_ID = "file-chapter-master"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "commerce-export.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    try:
        yield sm
    finally:

        async def _dispose() -> None:
            await engine.dispose()

        asyncio.run(_dispose())


@pytest.fixture
def patched(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)

    async def _never_cancel(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never_cancel)
    return session_local


async def _seed_variant_with_master(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """种入 Project / Chapter / StoryFormula / StoryVariant /
    PlatformExportPreset / 章节成片 FileItem + FileUsage。
    """

    async with sm() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="W23 commerce export test",
                style=ProjectStyle.real_people_city,
            )
        )
        db.add(
            Chapter(
                id=_CHAPTER_ID,
                project_id=_PROJECT_ID,
                index=1,
                title="测试章",
            )
        )
        db.add(
            PromptTemplate(
                id=_PROMPT_TEMPLATE_ID,
                category=PromptCategory.story_formula_generator,
                name="t",
                preview="",
                content="x",
                variables=[],
            )
        )
        db.add(
            StoryFormula(
                id=_FORMULA_ID,
                name="test-formula",
                region=FormulaRegion.cn,
                category="cn_viral",
                prompt_template_id=_PROMPT_TEMPLATE_ID,
            )
        )
        db.add(
            StoryVariant(
                id=_VARIANT_ID,
                project_id=_PROJECT_ID,
                chapter_id=_CHAPTER_ID,
                formula_id=_FORMULA_ID,
            )
        )
        db.add(
            PlatformExportPreset(
                id=_PRESET_ID,
                name="抖音默认（测试）",
                platform=Platform.douyin,
                aspect_ratio="9:16",
                max_duration_sec=60,
                subtitle_style_id=None,
                voice_pack_id=None,
                watermark_file_id=None,
                sticker_specs=[],
                file_format="mp4",
                codec_preset="h264_high_4_1",
                loudness_lufs=-16.0,
                is_system=True,
                sort_order=0,
                description="",
            )
        )
        db.add(
            FileItem(
                id=_MASTER_FILE_ID,
                type=FileType.video,
                name="chapter master dubbed",
                thumbnail="",
                tags=["chapter_av_export"],
                storage_key=f"chapters/{_CHAPTER_ID}/master.mp4",
            )
        )
        db.add(
            FileUsage(
                file_id=_MASTER_FILE_ID,
                project_id=_PROJECT_ID,
                chapter_id=_CHAPTER_ID,
                shot_id=None,
                usage_kind=FileUsageKind.chapter_master_dubbed.value,
                source_ref=f"chapter:{_CHAPTER_ID}:av_export:bootstrap",
            )
        )
        await db.commit()


async def _seed_generation_task(
    sm: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
) -> None:
    async with sm() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={
                    "task_kind": TASK_KIND,
                    "run_args": {
                        "variant_id": _VARIANT_ID,
                        "preset_id": _PRESET_ID,
                    },
                },
                result=None,
                error="",
            )
        )
        await db.commit()


def _install_io_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过真实 S3 + ffmpeg：占位字节流 + 直接写空 mp4。"""

    async def _upload(*, key: str, **_: Any) -> StoredFileInfo:
        return StoredFileInfo(
            key=key,
            url=f"https://cdn.example.com/{key}",
            size=2048,
            content_type="video/mp4",
        )

    async def _download(*, key: str) -> bytes:  # noqa: ARG001 - 接口约束
        return b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024

    async def _fake_run_ffmpeg(args: list[str]) -> None:
        # args 末尾是输出路径；写个非空字节让 worker 的 read_bytes 通过。
        output = Path(args[-1])
        output.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"OUT" + b"\x00" * 256)

    monkeypatch.setattr(worker_mod.storage, "upload_file", _upload)
    monkeypatch.setattr(worker_mod.storage, "download_file", _download)
    monkeypatch.setattr(worker_mod, "_run_ffmpeg", _fake_run_ffmpeg)


def test_executor_registered_with_commerce_export_task_kind() -> None:
    """``task_executor_registry.resolve("commerce_export")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND == "commerce_export"


def test_executor_timeout_set_to_1800s() -> None:
    """slow 队列超时上限：1800s（与 chapter_av_export 同档）。"""

    executor = build_commerce_export_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 1800.0
    assert executor.task_kind == TASK_KIND


@pytest.mark.asyncio
async def test_runner_rejects_missing_variant_id() -> None:
    with pytest.raises(RuntimeError, match="variant_id"):
        await run_commerce_export_task(
            "task-x", {"variant_id": "", "preset_id": "p"}
        )


@pytest.mark.asyncio
async def test_runner_rejects_missing_preset_id() -> None:
    with pytest.raises(RuntimeError, match="preset_id"):
        await run_commerce_export_task(
            "task-x", {"variant_id": "v", "preset_id": ""}
        )


@pytest.mark.asyncio
async def test_worker_lifecycle_running_to_succeeded(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整生命周期：pending → running → succeeded，progress=100，result 完整。"""

    _install_io_mocks(monkeypatch)
    await _seed_variant_with_master(patched)

    task_id = "task-w23-export-happy"
    await _seed_generation_task(patched, task_id=task_id)

    await run_commerce_export_task(
        task_id,
        {"variant_id": _VARIANT_ID, "preset_id": _PRESET_ID},
    )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.succeeded
        assert main.progress == 100
        result = main.result or {}
        assert result["variant_id"] == _VARIANT_ID
        assert result["preset_id"] == _PRESET_ID
        assert result["platform"] == Platform.douyin.value
        assert result["aspect_ratio"] == "9:16"
        assert result["codec_preset"] == "h264_high_4_1"
        assert result["file_id"], "result.file_id 必须落到新 FileItem"


@pytest.mark.asyncio
async def test_worker_writes_FileItem_with_usage_kind_product_export(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路径会落 1 行 product_export FileUsage，source_ref 编码 (variant, preset, task)。"""

    _install_io_mocks(monkeypatch)
    await _seed_variant_with_master(patched)

    task_id = "task-w23-export-fileusage"
    await _seed_generation_task(patched, task_id=task_id)

    await run_commerce_export_task(
        task_id,
        {"variant_id": _VARIANT_ID, "preset_id": _PRESET_ID},
    )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        new_file_id = (main.result or {})["file_id"]

        new_file = await db.get(FileItem, new_file_id)
        assert new_file is not None
        assert new_file.type == FileType.video
        assert "commerce_export" in new_file.tags

        rows = (
            await db.execute(
                select(FileUsage).where(
                    FileUsage.file_id == new_file_id,
                    FileUsage.usage_kind == FileUsageKind.product_export.value,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        usage = rows[0]
        assert usage.project_id == _PROJECT_ID
        assert usage.chapter_id == _CHAPTER_ID
        assert _VARIANT_ID in (usage.source_ref or "")
        assert _PRESET_ID in (usage.source_ref or "")
        assert task_id in (usage.source_ref or "")


@pytest.mark.asyncio
async def test_worker_marks_failed_when_master_missing(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """章节没有 chapter_master_dubbed 文件时必须落 failed 而非静默成功。"""

    _install_io_mocks(monkeypatch)
    # 仅种 variant + preset，不种 master FileItem / FileUsage。
    async with patched() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="empty",
                style=ProjectStyle.real_people_city,
            )
        )
        db.add(
            Chapter(
                id=_CHAPTER_ID,
                project_id=_PROJECT_ID,
                index=1,
                title="t",
            )
        )
        db.add(
            PromptTemplate(
                id=_PROMPT_TEMPLATE_ID,
                category=PromptCategory.story_formula_generator,
                name="t",
                preview="",
                content="x",
                variables=[],
            )
        )
        db.add(
            StoryFormula(
                id=_FORMULA_ID,
                name="x",
                region=FormulaRegion.cn,
                category="cn_viral",
                prompt_template_id=_PROMPT_TEMPLATE_ID,
            )
        )
        db.add(
            StoryVariant(
                id=_VARIANT_ID,
                project_id=_PROJECT_ID,
                chapter_id=_CHAPTER_ID,
                formula_id=_FORMULA_ID,
            )
        )
        db.add(
            PlatformExportPreset(
                id=_PRESET_ID,
                name="t",
                platform=Platform.douyin,
                aspect_ratio="9:16",
                max_duration_sec=60,
                subtitle_style_id=None,
                voice_pack_id=None,
                watermark_file_id=None,
                sticker_specs=[],
                file_format="mp4",
                codec_preset="h264_high_4_1",
                loudness_lufs=-16.0,
                is_system=True,
                sort_order=0,
                description="",
            )
        )
        await db.commit()

    task_id = "task-w23-export-no-master"
    await _seed_generation_task(patched, task_id=task_id)

    with pytest.raises(RuntimeError, match="chapter_av_export"):
        await run_commerce_export_task(
            task_id,
            {"variant_id": _VARIANT_ID, "preset_id": _PRESET_ID},
        )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.failed
        assert "chapter_av_export" in (main.error or "")
