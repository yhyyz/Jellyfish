"""``/api/v1/login/*`` 鉴权入口（P5 W32-T5 引入）。

承载 OAuth2 password flow 的登录 endpoint：

- ``POST /access-token``：username + password → JWT access token

错误处理约定（避免用户枚举）：
- 用户不存在 / 密码错误 → 统一 401 ``Incorrect username or password``
- ``is_active=False`` → 400 ``Inactive user``（这条 OK 暴露，因为前提是
  username + password 已正确）

实现遵循 AGENTS.md §4：
- 路由层负责收参（``OAuth2PasswordRequestForm`` 解 form data）/ 调 service
  / 组织 ``ApiResponse`` 响应壳；
- 业务逻辑（用户查询、密码 verify、自动哈希升级）下沉到
  :mod:`app.services.auth.user_service`。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token
from app.dependencies import get_db
from app.schemas.auth.token import Token
from app.schemas.common import ApiResponse, success_response
from app.services.auth.user_service import authenticate_user


router = APIRouter()


@router.post(
    "/access-token",
    response_model=ApiResponse[Token],
    summary="登录获取 JWT access token（OAuth2 password flow）",
)
async def login_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[Token]:
    """以 username + password 登录，颁发 HS256 编码的 JWT access token。

    - 输入：OAuth2 标准 form data（``username`` + ``password``）。
    - 输出：``ApiResponse[Token]``，含 ``access_token`` / ``token_type=bearer`` /
      ``expires_in`` 三字段。

    Raises:
        HTTPException 401: 用户不存在或密码错误（统一消息）。
        HTTPException 400: 用户存在但 ``is_active=False``。
    """

    user = await authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    expires_in = settings.access_token_expire_minutes * 60
    access_token = create_access_token(user.id)
    return success_response(
        Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        )
    )
