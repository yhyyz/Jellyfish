"""字幕样式只读接口（W20-T0b，P3 W18 配套）。

仅暴露列表 GET 路径：

- ``GET /api/v1/commerce/subtitle-styles``：按 ``is_system`` / ``format`` /
  ``project_id`` 三轴过滤系统级（DOUYIN_DEFAULT / TIKTOK_VIRAL /
  REELS_LOWER_THIRD）与潜在用户自定义样式；默认按 ``is_system DESC`` +
  ``sort_order ASC`` + ``name ASC`` 三层稳定排序，让前端
  SubtitleStylePicker 直接消费。

``alignment`` 字段已由 service 层从 ``SubtitleAlignment`` 字符串枚举
（``bottom_center`` 等）换算为 ASS Style 行的 numpad int（1-9），便于
前端预览组件直接对照 ASS 渲染坐标系。

写入路径不开放给 API：系统级 seed 由
:func:`app.services.studio.builtin_subtitle_styles.bootstrap_builtin_subtitle_styles`
在启动期幂等加载；项目级覆盖样式将在后续 wave 通过专门的项目设置面
板暴露，均不在本路由职责内。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.subtitle_styles import SubtitleStyleRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.subtitle_styles import list_subtitle_styles

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
        description="项目级覆盖样式 ID（前向兼容预留，当前 ORM 暂无 project_id 列，传值与不传等价）",
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
