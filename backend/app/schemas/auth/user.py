"""User schemas（P5 W32-T10 引入）。

UserRead / UserCreate / UserUpdate Pydantic 模型；
``hashed_password`` 永远不出现在响应中（避免泄漏）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import UserRole


class UserRead(BaseModel):
    """用户信息读响应（不包含 hashed_password）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID hex string")
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """admin 创建用户的请求体。"""

    username: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=6, max_length=128)
    role: UserRole = UserRole.MEMBER
    is_active: bool = True


class UserUpdate(BaseModel):
    """admin 更新用户的请求体（所有字段可选；password 单独走也走此入口）。"""

    email: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
