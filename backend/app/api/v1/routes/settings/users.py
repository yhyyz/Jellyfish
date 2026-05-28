"""``/api/v1/settings/users/*`` admin 用户管理（P5 W32-T10 引入）。

router-level ``dependencies=[Depends(require_admin)]`` 守护整个子树：
- GET    /        列表（filter by role/is_active + pagination）
- POST   /        创建用户
- PATCH  /{id}    更新（role / is_active / email / password 可选）
- DELETE /{id}    软删除（is_active=False；admin 不能删自己）

实现遵循 AGENTS.md §4：路由层只做收参/调 service/包装 ApiResponse；
业务校验（唯一性 / 不能删自己）下沉到 :mod:`app.services.auth.user_admin_service`。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_db, require_admin
from app.schemas.auth.user import UserCreate, UserRead, UserUpdate
from app.schemas.common import (
    ApiResponse,
    PaginatedData,
    Pagination,
    created_response,
    empty_response,
    success_response,
)
from app.models.types import UserRole
from app.services.auth.user_admin_service import (
    CannotDeleteSelfError,
    UserConflictError,
    UserNotFoundError,
    create_user,
    list_users,
    soft_delete_user,
    update_user,
)


router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "",
    response_model=ApiResponse[PaginatedData[UserRead]],
    summary="列出用户（分页 + role / is_active 过滤）",
)
async def list_users_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> ApiResponse[PaginatedData[UserRead]]:
    """admin 列表查询，默认按 ``created_at DESC`` 排序。"""

    items, total = await list_users(
        db,
        role=role,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    max_page = max(1, (total + page_size - 1) // page_size)
    pagination = Pagination(
        page=page, page_size=page_size, total=total, max_page=max_page
    )
    data = PaginatedData[UserRead](
        items=[UserRead.model_validate(item) for item in items],
        pagination=pagination,
    )
    return success_response(data)


@router.post(
    "",
    response_model=ApiResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建用户",
)
async def create_user_endpoint(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserRead]:
    """admin 创建一条新用户行。username / email 已存在 → 409。"""

    try:
        user = await create_user(db, payload)
    except UserConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    return created_response(UserRead.model_validate(user))


@router.patch(
    "/{user_id}",
    response_model=ApiResponse[UserRead],
    summary="更新用户（email / role / is_active / password 可选）",
)
async def update_user_endpoint(
    user_id: str,
    payload: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserRead]:
    """admin 更新指定 user 的可变字段。"""

    try:
        user = await update_user(db, user_id=user_id, payload=payload)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    except UserConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    return success_response(UserRead.model_validate(user))


@router.delete(
    "/{user_id}",
    response_model=ApiResponse[None],
    summary="软删除用户（is_active=False）",
)
async def soft_delete_user_endpoint(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
) -> ApiResponse[None]:
    """admin 软删除指定 user；admin 不允许删除自己。"""

    try:
        await soft_delete_user(
            db, user_id=user_id, current_user_id=current_user.id
        )
    except CannotDeleteSelfError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return empty_response()
