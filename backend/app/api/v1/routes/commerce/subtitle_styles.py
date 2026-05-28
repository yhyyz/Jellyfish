"""字幕样式接口（W20-T0b 列表 + W30-T3 项目级 CRUD）。

历史只读端点（W20-T0b）：

- ``GET /api/v1/commerce/subtitle-styles``：按 ``is_system`` / ``format`` /
  ``project_id`` 三轴过滤系统级（DOUYIN_DEFAULT / TIKTOK_VIRAL /
  REELS_LOWER_THIRD）与潜在用户自定义样式；默认按 ``is_system DESC`` +
  ``sort_order ASC`` + ``name ASC`` 三层稳定排序，让前端
  SubtitleStylePicker 直接消费。

W30 新增项目级 CRUD：

- ``GET    /api/v1/commerce/projects/{project_id}/subtitle-styles``：merged
  视图（系统级 + 项目级覆盖）。
- ``POST   /api/v1/commerce/projects/{project_id}/subtitle-styles``：创建
  项目级覆盖样式。
- ``PATCH  /api/v1/commerce/projects/{project_id}/subtitle-styles/{style_id}``：
  更新项目级覆盖样式。
- ``DELETE /api/v1/commerce/projects/{project_id}/subtitle-styles/{style_id}``：
  删除项目级覆盖样式（"重置为系统模板"）。

``alignment`` 字段在 service 层从 ``SubtitleAlignment`` 字符串枚举
（``bottom_center`` 等）换算为 ASS Style 行的 numpad int（1-9），便于
前端预览组件直接对照 ASS 渲染坐标系；写入路径反向把 numpad int 还原
为枚举。

按 AGENTS.md §4 严格分层：路由层只做收参 / 调 service / 包装
``ApiResponse``；业务校验（系统级 immutable / 同 project name 唯一 / FK
存在性）全部下沉到 ``app/services/commerce/subtitle_styles``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.subtitle_styles import (
    ProjectSubtitleStyleCreateInput,
    ProjectSubtitleStyleUpdateInput,
    SubtitleStyleRead,
)
from app.schemas.common import (
    ApiResponse,
    created_response,
    empty_response,
    success_response,
)
from app.services.commerce.subtitle_styles import (
    create_project_subtitle_style,
    delete_project_subtitle_style,
    list_project_subtitle_styles,
    list_subtitle_styles,
    update_project_subtitle_style,
)

router = APIRouter()


@router.get(
    "/subtitle-styles",
    response_model=ApiResponse[list[SubtitleStyleRead]],
    summary="字幕样式列表（按系统级 / 文件格式 / 项目过滤）",
)
async def list_subtitle_styles_endpoint(
    db: AsyncSession = Depends(get_db),
    is_system: bool | None = Query(
        None,
        description="是否只列系统级 seed；true=仅系统 / false=仅用户自定义 / 缺省=全部",
    ),
    format: str | None = Query(  # noqa: A002 (与 OpenAPI 字段保持一致)
        None,
        description="按字幕文件格式过滤（ass / srt / vtt）",
    ),
    project_id: str | None = Query(
        None,
        description=(
            "项目级覆盖样式 ID 过滤（W30：传值缩窄到该 project 的覆盖样式；"
            "缺省时返回系统级 + 全部项目级）"
        ),
    ),
) -> ApiResponse[list[SubtitleStyleRead]]:
    """列出 ``subtitle_styles`` 表中的全部记录。

    路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
    ``success_response``，不在此处做业务过滤或字段映射。service 层已把
    ``alignment`` 换算为 ASS numpad int，本路由直接 dict-validate 即可。
    """

    items = await list_subtitle_styles(
        db,
        is_system=is_system,
        format=format,
        project_id=project_id,
    )
    return success_response([SubtitleStyleRead.model_validate(item) for item in items])


@router.get(
    "/projects/{project_id}/subtitle-styles",
    response_model=ApiResponse[list[SubtitleStyleRead]],
    summary="项目级 merged 字幕样式视图（系统级 + 项目级覆盖）",
)
async def list_project_subtitle_styles_endpoint(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SubtitleStyleRead]]:
    """列出指定 project 视角下的字幕样式 merged 视图。

    merged 语义：项目级同名行覆盖系统级 seed；项目级独有 name 单独列出。
    """

    items = await list_project_subtitle_styles(db, project_id=project_id)
    return success_response(
        [SubtitleStyleRead.model_validate(item) for item in items]
    )


@router.post(
    "/projects/{project_id}/subtitle-styles",
    response_model=ApiResponse[SubtitleStyleRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建项目级覆盖字幕样式",
)
async def create_project_subtitle_style_endpoint(
    project_id: str,
    payload: ProjectSubtitleStyleCreateInput,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SubtitleStyleRead]:
    """创建一条项目级覆盖样式行。

    业务约束：
        - ``project_id`` 必须存在（404 if not found）；
        - 同 project 内 ``name`` 唯一（409 on conflict）；
        - 系统级行的 POST 路径不存在（仅项目 path 可创建项目级行）。
    """

    item = await create_project_subtitle_style(
        db, project_id=project_id, payload=payload
    )
    return created_response(SubtitleStyleRead.model_validate(item))


@router.patch(
    "/projects/{project_id}/subtitle-styles/{style_id}",
    response_model=ApiResponse[SubtitleStyleRead],
    summary="更新项目级覆盖字幕样式",
)
async def update_project_subtitle_style_endpoint(
    project_id: str,
    style_id: str,
    payload: ProjectSubtitleStyleUpdateInput,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SubtitleStyleRead]:
    """部分更新项目级覆盖样式。

    业务约束：
        - 系统级行（``project_id IS NULL``）→ 403 immutable；
        - 行不存在 / 行不属于该 project → 404；
        - rename 后与同 project 内已有 name 冲突 → 409。
    """

    item = await update_project_subtitle_style(
        db, project_id=project_id, style_id=style_id, payload=payload
    )
    return success_response(SubtitleStyleRead.model_validate(item))


@router.delete(
    "/projects/{project_id}/subtitle-styles/{style_id}",
    response_model=ApiResponse[None],
    summary="删除项目级覆盖字幕样式（重置为系统模板）",
)
async def delete_project_subtitle_style_endpoint(
    project_id: str,
    style_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """删除项目级覆盖样式行。

    删除后下次渲染会自动 fallback 系统级；已渲染的 SubtitleTrack
    保留 SET NULL 引用（W18 ORM ``ondelete='SET NULL'``），不会出现悬挂错误。

    业务约束同 PATCH：系统级 immutable / 行归属校验。
    """

    await delete_project_subtitle_style(
        db, project_id=project_id, style_id=style_id
    )
    return empty_response()
