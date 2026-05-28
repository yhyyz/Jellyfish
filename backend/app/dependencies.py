"""FastAPI 依赖注入。"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db import async_session_maker
from app.core.security import decode_access_token
from app.models.types import UserRole
from app.models.user import User
from app.services.llm.resolver import build_default_text_llm


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """提供异步数据库会话。"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_llm(db: AsyncSession = Depends(get_db)) -> BaseChatModel:
    """提供默认文本 LLM（ChatOpenAI）。"""
    return await build_default_text_llm(db, thinking=True)

async def get_nothinking_llm(db: AsyncSession = Depends(get_db)) -> BaseChatModel:
    """提供默认文本 LLM（ChatOpenAI，禁用 thinking）。"""
    return await build_default_text_llm(db, thinking=False)


reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/v1/login/access-token", auto_error=False
)


_STATIC_ADMIN_USER = User(
    id="__static_fallback__",
    username="__static_admin__",
    email="static-admin@jellyfish.local",
    hashed_password="",
    role=UserRole.ADMIN,
    is_active=True,
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(reusable_oauth2)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """根据 JWT 或 Stage-1 静态 ``api_key`` fallback 解析当前用户（P5 W32-T6）。

    Stage-1 双轨策略（``settings.jwt_fallback_to_static`` 控制）：

    1. **JWT 路径（首选）**：从 ``Authorization: Bearer <jwt>`` 解析 token,
       ``decode_access_token`` 拿到 ``sub=user.id``，``session.get(User, id)``
       识别身份；用户不存在 → 401，``is_active=False`` → 403。
    2. **静态 fallback（过渡期）**：``jwt_fallback_to_static=True`` 且
       ``Authorization`` 头为 ``Bearer <settings.api_key>`` 时，映射到一个
       内存虚拟 admin 用户（id=``__static_fallback__``，不入库）。
       Stage-3（P6+）会删掉这条分支。
    3. 都没命中 → 401。

    设计要点：
        - JWT claims 故意不放 ``role``，这里**每请求**都 ``session.get`` 查 DB,
          identity map 命中 O(1)，确保用户被降权时旧 token 立即失效。
        - 静态 fallback 不入库：避免污染真实 ``users`` 表，且
          ``__static_fallback__`` id 在数据库 UUID 命名空间外不可碰撞。
    """

    if token:
        try:
            user_id = decode_access_token(token)
        except InvalidTokenError as exc:
            if (
                settings.jwt_fallback_to_static
                and settings.api_key
                and token == settings.api_key
            ):
                return _STATIC_ADMIN_USER
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = await db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )
        return user

    if (
        settings.jwt_fallback_to_static
        and settings.api_key
        and authorization
        and authorization.startswith("Bearer ")
        and authorization.removeprefix("Bearer ") == settings.api_key
    ):
        return _STATIC_ADMIN_USER

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed_roles: UserRole):
    """Dependency factory：守卫端点只允许指定 role 的用户访问（P5 W32-T6）。

    用法 A（router-level，整个子树）：
        ``APIRouter(dependencies=[Depends(require_role(UserRole.ADMIN))])``

    用法 B（端点级，同时拿 user 对象）：
        ``async def read_users_me(user: User = Depends(require_role(UserRole.ADMIN)))``

    Args:
        *allowed_roles: 允许访问的角色集合（按精确匹配，不做 admin > member
            隐含放行；隐含放行由 ``require_member = require_role(ADMIN, MEMBER)``
            这类别名显式声明，避免歧义）。

    Returns:
        async closure，签名 ``(current_user: CurrentUser) -> User``，可直接
        放到 ``Depends(...)`` 里。
    """

    async def role_checker(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Operation requires one of roles: "
                    f"{[r.value for r in allowed_roles]}"
                ),
            )
        return current_user

    return role_checker


require_admin = require_role(UserRole.ADMIN)
require_member = require_role(UserRole.ADMIN, UserRole.MEMBER)


class _ImageHttpRunnable:
    """最小图片生成 runnable：从环境变量读取配置，通过 HTTP 调用外部图片生成服务。"""

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    def invoke(self, payload: dict) -> dict:  # noqa: ANN001
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise HTTPException(status_code=503, detail="Install httpx to enable image generation") from e
        with httpx.Client(timeout=self._timeout_s) as client:
            r = client.post(
                self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"images": data}

    async def ainvoke(self, payload: dict) -> dict:  # noqa: ANN001
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise HTTPException(status_code=503, detail="Install httpx to enable image generation") from e
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.post(
                self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"images": data}
