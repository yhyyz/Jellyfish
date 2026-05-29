"""Chapter CRUD（从 projects.py 拆分）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.dependencies import get_db
from app.models.studio import Chapter, Project, Shot
from app.schemas.common import ApiResponse, PaginatedData, created_response, empty_response, paginated_response, success_response
from app.services.common import (
    create_and_refresh,
    delete_if_exists,
    entity_already_exists,
    entity_not_found,
    ensure_not_exists,
    flush_and_refresh,
    get_or_404,
    patch_model,
    require_entity,
)
from app.schemas.studio.chapter_timeline import (
    ChapterTimelineRead,
    ChapterTimelineSegmentAudioPatch,
    ChapterTimelineSegmentRead,
    ChapterTimelineWrite,
)
from app.schemas.studio.projects import ChapterCreate, ChapterRead, ChapterUpdate
from app.services.studio.chapter_timeline import (
    SegmentNotFoundError,
    TimelineLayoutConflictError,
    build_timeline_read,
    patch_segment_audio,
    replace_timeline_segments,
)

router = APIRouter()

CHAPTER_ORDER_FIELDS = {"index", "title", "created_at", "updated_at", "storyboard_count", "status"}


@router.get(
    "/{chapter_id}/timeline",
    response_model=ApiResponse[ChapterTimelineRead],
    summary="获取章节剪辑时间线（含镜头成片解析状态）",
)
async def get_chapter_timeline(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterTimelineRead]:
    await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    data = await build_timeline_read(db, chapter_id)
    return success_response(data)


@router.put(
    "/{chapter_id}/timeline",
    response_model=ApiResponse[ChapterTimelineRead],
    summary="全量保存章节剪辑时间线片段顺序",
)
async def put_chapter_timeline(
    chapter_id: str,
    body: ChapterTimelineWrite,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterTimelineRead]:
    await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    try:
        data = await replace_timeline_segments(db, chapter_id, body)
    except TimelineLayoutConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "layout_version conflict",
                "server_layout_version": exc.server_version,
                "client_layout_version": exc.client_version,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return success_response(data)


@router.patch(
    "/{chapter_id}/timeline/segments/{segment_id}/audio",
    response_model=ApiResponse[ChapterTimelineSegmentRead],
    summary="P5 W31-T8：偏量更新单 segment 的 BGM/SFX/ducking 字段",
)
async def patch_chapter_timeline_segment_audio(
    chapter_id: str,
    segment_id: str,
    body: ChapterTimelineSegmentAudioPatch,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterTimelineSegmentRead]:
    """偏量更新本段 BGM/SFX/ducking 字段（不动 layout_version、不动其它段）。

    与 ``PUT /timeline``（全量替换）的语义区分：
    - PUT 改顺序、入出点、字幕/TTS/BGM 等任意字段，``layout_version`` +1；
    - PATCH 只动一段三列，避免乐观锁误冲突，专给 AVPreviewPanel UI 选 BGM
      / 拖 ducking 滑块时高频写回使用。

    422：``bgm_ducking_db`` 不在 ``[-30, 0]`` 范围内由 Pydantic 自动校验。
    404：``chapter_id`` 不存在 / segment 不存在 / segment 不属于该 chapter。
    W19b 事务边界：service 层只 ``flush``，本路由统一 ``commit``，异常时
    整条请求 rollback。
    """

    await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    try:
        data = await patch_segment_audio(
            db, chapter_id=chapter_id, segment_id=segment_id, body=body
        )
    except SegmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("ChapterTimelineSegment"),
        ) from exc
    await db.commit()
    return success_response(data)


@router.get(
    "",
    response_model=ApiResponse[PaginatedData[ChapterRead]],
    summary="章节列表（分页）",
)
async def list_chapters(
    db: AsyncSession = Depends(get_db),
    project_id: str | None = Query(None, description="按项目过滤"),
    q: str | None = Query(None, description="关键字，过滤 title/summary"),
    order: str | None = Query(None, description="排序字段"),
    is_desc: bool = Query(False, description="是否倒序"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ChapterRead]]:
    stmt = select(Chapter)
    if project_id:
        stmt = stmt.where(Chapter.project_id == project_id)
    stmt = apply_keyword_filter(stmt, q=q, fields=[Chapter.title, Chapter.summary])
    stmt = apply_order(
        stmt,
        model=Chapter,
        order=order,
        is_desc=is_desc,
        allow_fields=CHAPTER_ORDER_FIELDS,
        default="index",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)

    chapter_ids = [c.id for c in items]
    shot_count_by_chapter: dict[str, int] = {}
    if chapter_ids:
        count_stmt = (
            select(Shot.chapter_id, func.count(Shot.id))
            .where(Shot.chapter_id.in_(chapter_ids))
            .group_by(Shot.chapter_id)
        )
        res = await db.execute(count_stmt)
        shot_count_by_chapter = {str(ch_id): int(cnt) for ch_id, cnt in res.all()}

    return paginated_response(
        [
            ChapterRead.model_validate(x).model_copy(update={"shot_count": shot_count_by_chapter.get(x.id, 0)})
            for x in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "",
    response_model=ApiResponse[ChapterRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建章节",
)
async def create_chapter(
    body: ChapterCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    await ensure_not_exists(
        db,
        Chapter,
        body.id,
        detail=entity_already_exists("Chapter"),
    )
    await require_entity(
        db,
        Project,
        body.project_id,
        detail=entity_not_found("Project"),
        status_code=400,
    )
    obj = await create_and_refresh(db, Chapter(**body.model_dump()))
    return created_response(ChapterRead.model_validate(obj))


@router.get(
    "/{chapter_id}",
    response_model=ApiResponse[ChapterRead],
    summary="获取章节",
)
async def get_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    obj = await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    count_stmt = select(func.count(Shot.id)).where(Shot.chapter_id == chapter_id)
    res = await db.execute(count_stmt)
    shot_count = int(res.scalar() or 0)
    return success_response(ChapterRead.model_validate(obj).model_copy(update={"shot_count": shot_count}))


@router.patch(
    "/{chapter_id}",
    response_model=ApiResponse[ChapterRead],
    summary="更新章节",
)
async def update_chapter(
    chapter_id: str,
    body: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    obj = await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    update = body.model_dump(exclude_unset=True)
    if "project_id" in update:
        await require_entity(
            db,
            Project,
            update["project_id"],
            detail=entity_not_found("Project"),
            status_code=400,
        )
    patch_model(obj, update)
    await flush_and_refresh(db, obj)
    return success_response(ChapterRead.model_validate(obj))


@router.delete(
    "/{chapter_id}",
    response_model=ApiResponse[None],
    summary="删除章节",
)
async def delete_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_if_exists(db, Chapter, chapter_id)
    return empty_response()
