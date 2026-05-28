"""鉴权加密层（P5 W32-T4 引入）。

为什么独立成层：
    集中放置密码哈希、JWT issue/verify 实现，避免散落到 api/service 层。
    AGENTS.md §4 明确要求 ``service`` 不直接 import jwt 或 pwdlib——所有
    鉴权细节走 :mod:`app.core.security`，便于将来切换算法（HS256→RS256
    或 argon2→argon2id v2）时一处修改全局生效。

为什么用 pwdlib 而不是 passlib：
    passlib 在 2024 起停止维护，不再支持新版 Python；pwdlib 是社区接力
    的 modern 替代品，API 与 passlib 兼容度高，原生支持 argon2 默认参数
    （OWASP 2023 推荐）+ ``verify_and_update`` 自动迁移旧哈希。

为什么 JWT 不放 role：
    用户被降权后旧 token 仍 admin 会出严重安全事故。本层 ``create_access_token``
    只把 ``sub=user.id`` 写进 claims，``decode_access_token`` 也只解出 user.id；
    role 检查由 :mod:`app.dependencies` 在每个请求里 ``session.get(User, id)``
    做 identity-map 查询（O(1)），保证降权立即生效。

为什么 HS256 而不是 RS256：
    单实例部署不需要公私钥分离；切换到多实例 / 多服务下发场景时再换 RS256。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.config import settings


_password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))

ALGORITHM = "HS256"


def hash_password(plain_password: str) -> str:
    """对明文密码做 argon2 哈希。

    Args:
        plain_password: 用户输入明文，长度推荐 ≥ 8。

    Returns:
        argon2 哈希字符串（含 salt + 算法参数前缀，可直接持久化到 DB）。
    """

    return _password_hash.hash(plain_password)


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """校验明文与哈希是否匹配，并支持自动哈希升级。

    Returns:
        ``(ok, new_hash)`` 元组：

        - ``ok=True, new_hash=None``：密码正确，且已是最新算法（argon2）。
        - ``ok=True, new_hash=str``：密码正确但哈希为旧算法（如 bcrypt）；
          调用方应将 ``new_hash`` 写回 DB 完成无感迁移。
        - ``ok=False, new_hash=None``：密码错误。
    """

    return _password_hash.verify_and_update(plain_password, hashed_password)


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> str:
    """颁发 HS256 编码的 JWT access token。

    Args:
        subject: 通常是 ``user.id``（UUID hex string），写入 ``sub`` claim。
        expires_delta: 自定义过期时长；缺省取 ``settings.access_token_expire_minutes``。

    Returns:
        JWT 字符串（``header.payload.signature``）。

    设计约束：
        本函数故意只写 ``exp`` 与 ``sub`` 两个 claim。``role`` 不放是核心安全
        约束（见模块 docstring）；其它如 ``iss`` / ``aud`` 在单实例部署下不必
        要，未来切多服务时再扩。
    """

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload: dict[str, Any] = {"exp": expire, "sub": str(subject)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """解码并验证 JWT，返回 ``sub`` claim（user.id）。

    Args:
        token: 来自 ``Authorization: Bearer <token>`` 头部的 JWT 字符串。

    Returns:
        ``sub`` claim 的字符串值（user.id）。

    Raises:
        InvalidTokenError: token 无效（签名错 / 过期 / 缺失 ``sub`` claim）。
    """

    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    sub = payload.get("sub")
    if not sub:
        raise InvalidTokenError("Missing 'sub' claim")
    return str(sub)
