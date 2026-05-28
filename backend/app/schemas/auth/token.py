"""Token / Login schemas（P5 W32-T5 引入）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Token(BaseModel):
    """登录成功后的 access token 响应载荷。

    序列化遵循 OAuth2 password flow 习惯：
    - ``access_token``：JWT 字符串本体；
    - ``token_type``：固定为 ``"bearer"``；
    - ``expires_in``：剩余有效秒数（前端可用作自动登出倒计时）。
    """

    access_token: str = Field(..., description="JWT access token (HS256)")
    token_type: str = Field("bearer", description="Token 类型，固定为 bearer")
    expires_in: int = Field(
        ..., description="剩余有效秒数（与 ACCESS_TOKEN_EXPIRE_MINUTES 一致）"
    )
