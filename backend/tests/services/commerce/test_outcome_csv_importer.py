"""StoryOutcome CSV importer service 单元测试（W22-T2，P4 Wave B 1/11）。

TDD 覆盖（≥ 4）：

1. ``test_douyin_mapping_translates_chinese_headers``：抖音 profile 把
   ``播放量`` → ``plays``、``点赞数`` → ``interactions``、``GMV`` →
   ``gmv``，正确写入 ``story_outcomes``。
2. ``test_xhs_completion_rate_percent_to_decimal``：``"85%"`` 被解析为
   ``0.85``；``"78%"`` → ``0.78``。
3. ``test_malformed_row_recorded_in_errors_not_aborting_others``：恶意
   行（缺 variant_id / 非数字 plays / 越界完播率 / 负 gmv）被收集到
   ``errors``，但合法行仍写入。
4. ``test_5mb_file_streamed_without_loading_full_into_memory``：构造一
   个 4MB+ 的 CSV，验证 importer 不会把全部内容 read 进内存（通过
   ``InstrumentedStream.max_single_read`` 检查每次 read chunk 的上限）。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.models.story_formula import StoryOutcome, StoryVariant
from app.models.studio import Chapter, ChapterStatus, Project, ProjectStyle, ProjectVisualStyle
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import ProjectKind, PromptCategory, StoryVariantStatus
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    bootstrap_builtin_story_formulas,
)
from app.services.commerce.outcome_csv_importer import OutcomeCsvImporter


_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "_fixtures"


async def _build_session() -> AsyncGenerator[AsyncSession, None]:
    """构建内存 SQLite session 并写入 1 个 variant（var_alpha）。"""
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(
            PromptTemplate(
                id=BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
                category=PromptCategory.story_formula_generator,
                name="stub",
                preview="",
                content="",
                variables=[],
                is_default=False,
                is_system=True,
            )
        )
        session.add(
            Project(
                id="oc_proj",
                name="带货项目",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                seed=0,
                kind=ProjectKind.commerce_story.value,
                unify_style=True,
                progress=0,
                stats={},
            )
        )
        session.add(
            Chapter(
                id="oc_chap",
                project_id="oc_proj",
                index=1,
                title="第 1 章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        await session.commit()
        await bootstrap_builtin_story_formulas(session)
        session.add(
            StoryVariant(
                id="var_alpha",
                project_id="oc_proj",
                chapter_id="oc_chap",
                formula_id="underdog_triumph",
                script_full_text="",
                script_breakdown={},
                status=StoryVariantStatus.draft.value,
                is_champion=False,
                compliance_score=0,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _fixture_bytes(name: str) -> bytes:
    """读取 _fixtures 下的 CSV 字节流。

    把记录日期统一改写为今天前 1 天，避免 ``recorded_at <= now`` 校验
    在未来某天突然失败。原始 CSV 中固定写的是 ``2025-12-2X``，长期看
    可能被任意系统时钟当作"未来时间"——本函数只在内容包含 ``2025-12-``
    时做最小替换，保留原 fixture 文件不动以便人工检视。
    """
    raw = (_FIXTURES_DIR / name).read_bytes()
    text = raw.decode("utf-8")
    if "2025-12-" in text:
        # 把所有 2025-12-2X / 2025-12-1X 替换成今日（避免相对路径偏移）
        today = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        # 简单把 "2025-12-21".."2025-12-26" 全替换为今天
        for tail in ("21", "22", "23", "24", "25", "26"):
            text = text.replace(f"2025-12-{tail}", today)
    return text.encode("utf-8")


@pytest.mark.asyncio
async def test_douyin_mapping_translates_chinese_headers() -> None:
    """抖音 profile 把中文列名翻译到 StoryOutcomeCreate 字段并写入。"""
    async for db in _build_session():
        importer = OutcomeCsvImporter(db, mapping_profile="douyin")
        stream = io.BytesIO(_fixture_bytes("outcomes_douyin_sample.csv"))
        summary = await importer.import_stream(stream)
        await db.commit()

        assert summary.mapping_profile == "douyin"
        assert summary.total_rows == 3
        assert summary.inserted == 3
        assert summary.failed == 0

        rows = (
            (await db.execute(select(StoryOutcome).order_by(StoryOutcome.id.asc())))
            .scalars()
            .all()
        )
        assert [r.plays for r in rows] == [123456, 98765, 210000]
        # 第 3 行 "72%" / "38%" 解析成 0.72 / 0.38
        assert rows[2].completion_rate_3s == pytest.approx(0.72, rel=1e-6)
        assert rows[2].completion_rate_full == pytest.approx(0.38, rel=1e-6)
        # 互动量来自 "点赞数" 列
        assert rows[0].interactions == 2000
        assert rows[0].gmv == pytest.approx(1280.5, rel=1e-6)
        assert rows[0].platform == "douyin"


@pytest.mark.asyncio
async def test_xhs_completion_rate_percent_to_decimal() -> None:
    """小红书 profile 的 "85%" 被解析为 0.85（不出现 8500% 的笑话）。"""
    async for db in _build_session():
        importer = OutcomeCsvImporter(db, mapping_profile="xiaohongshu")
        stream = io.BytesIO(_fixture_bytes("outcomes_xhs_sample.csv"))
        summary = await importer.import_stream(stream)
        await db.commit()

        assert summary.total_rows == 2
        assert summary.inserted == 2
        assert summary.failed == 0

        rows = (
            (await db.execute(select(StoryOutcome).order_by(StoryOutcome.id.asc())))
            .scalars()
            .all()
        )
        assert rows[0].completion_rate_3s == pytest.approx(0.85, rel=1e-6)
        assert rows[0].completion_rate_full == pytest.approx(0.42, rel=1e-6)
        assert rows[1].completion_rate_3s == pytest.approx(0.78, rel=1e-6)
        # plays 字段来自 "曝光量" 列
        assert rows[0].plays == 55000
        assert rows[0].gmv == pytest.approx(580.0, rel=1e-6)
        assert rows[0].platform == "xiaohongshu"


@pytest.mark.asyncio
async def test_malformed_row_recorded_in_errors_not_aborting_others() -> None:
    """恶意行进入 errors[]，合法行仍被写入；整体不中断。"""
    async for db in _build_session():
        importer = OutcomeCsvImporter(db, mapping_profile="douyin")
        stream = io.BytesIO(_fixture_bytes("outcomes_malformed.csv"))
        summary = await importer.import_stream(stream)
        await db.commit()

        # 6 行数据：2 行合法（首 + 尾），4 行非法
        assert summary.total_rows == 6
        assert summary.inserted == 2
        assert summary.failed == 4
        assert len(summary.errors) == 4
        # row_index 严格 ≥ 2（header = 1）
        assert all(err.row_index >= 2 for err in summary.errors)
        # raw_row 必须被完整带回，前端可"原样回显"问题数据
        for err in summary.errors:
            assert isinstance(err.raw_row, dict)
            assert err.reason


@pytest.mark.asyncio
async def test_5mb_file_streamed_without_loading_full_into_memory() -> None:
    """importer 不会一次性 read() 整个 4MB+ 的 CSV 到内存。

    关键内部逻辑：用 ``InstrumentedStream`` 包装 ``BytesIO``，记录每次
    ``read(size)`` 的 size 上限。``csv.DictReader`` + ``TextIOWrapper``
    会按 8KB 量级分块读取；如果 importer 自己写了 ``data = f.read()``，
    单次 read 的 size 就会接近文件长度（>= 1MB），断言会失败。
    """
    # 构造一个略大于 1MB 的 CSV（避免真的写 4MB 让测试变慢）
    header = "variant_id,platform,plays,completion_rate_3s,completion_rate_full,interactions,cart_clicks,orders,gmv,notes,recorded_at\n"
    today = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    row = f"var_alpha,douyin,1000,0.5,0.3,100,10,5,200.0,note,{today}\n"
    # 重复直到 > 1MB
    body = header + row * 16000  # 16000 行 × ~60B ≈ 960KB+
    raw_bytes = body.encode("utf-8")
    assert len(raw_bytes) > 800_000, "fixture too small to exercise streaming"

    class _InstrumentedStream(io.BytesIO):
        """记录每次 read/read1 的 size 参数，验证 importer 是流式分块读取的。

        ``TextIOWrapper`` 通常调用底层缓冲对象的 ``read1`` 而非 ``read``，
        因此两个方法都需要拦截，避免 size 全是 0 让断言变成无效套套。
        """

        def __init__(self, buf: bytes) -> None:
            super().__init__(buf)
            self.max_single_read = 0
            self.total_calls = 0
            self._buf_len = len(buf)

        def read(self, size: int = -1) -> bytes:  # type: ignore[override]
            self.total_calls += 1
            self.max_single_read = max(self.max_single_read, size if size > 0 else self._buf_len)
            return super().read(size)

        def read1(self, size: int = -1) -> bytes:  # type: ignore[override]
            self.total_calls += 1
            self.max_single_read = max(self.max_single_read, size if size > 0 else self._buf_len)
            return super().read(size)

    stream = _InstrumentedStream(raw_bytes)

    async for db in _build_session():
        importer = OutcomeCsvImporter(db, mapping_profile="default")
        summary = await importer.import_stream(stream)
        await db.commit()

        assert summary.inserted == 16000
        # 单次 read 的 size 应远低于整个文件长度（流式 8KB / 64KB 量级）。
        assert stream.max_single_read < 256 * 1024, (
            f"importer 似乎一次性 read 整个文件，max_single_read="
            f"{stream.max_single_read}，total_calls={stream.total_calls}"
        )
        # 至少多次 read，证明确实是流式分块。
        assert stream.total_calls > 4


@pytest.mark.asyncio
async def test_unknown_variant_id_recorded_as_error() -> None:
    """variant_id 不存在 → 进入 errors，避免 FK 违反 abort 整个 batch。"""
    async for db in _build_session():
        importer = OutcomeCsvImporter(db, mapping_profile="default")
        today = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        body = (
            "variant_id,plays,gmv,recorded_at\n"
            f"var_alpha,100,10.0,{today}\n"
            f"var_unknown,200,20.0,{today}\n"
        ).encode("utf-8")
        summary = await importer.import_stream(io.BytesIO(body))
        await db.commit()

        assert summary.inserted == 1
        assert summary.failed == 1
        assert "var_unknown" in summary.errors[0].reason
