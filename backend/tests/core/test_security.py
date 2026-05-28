"""``app.core.security`` 单元测试（P5 W32-T4 引入）。

覆盖 6 个 case：
- happy path：argon2 hash + verify
- 错误密码 verify 失败
- 旧 bcrypt 哈希 verify 通过且返回新 argon2 hash（无感升级）
- create_access_token + decode_access_token round-trip
- 过期 token decode 抛 InvalidTokenError
- 篡改签名 token decode 抛 InvalidTokenError
"""

# pylint: disable=invalid-name

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.config import settings
from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password_happy_path() -> None:
    """argon2 哈希后验证通过，且不需要升级（new_hash 为 None）。"""
    plain = "correct horse battery staple"
    hashed = hash_password(plain)

    assert hashed != plain
    assert hashed.startswith("$argon2")

    ok, new_hash = verify_password(plain, hashed)
    assert ok is True
    assert new_hash is None


def test_verify_password_rejects_wrong_password() -> None:
    """错误密码 verify 应失败且不返回 new_hash。"""
    hashed = hash_password("right-pass-12345")
    ok, new_hash = verify_password("wrong-pass-12345", hashed)
    assert ok is False
    assert new_hash is None


def test_verify_password_upgrades_legacy_bcrypt_hash() -> None:
    """旧 bcrypt 哈希 verify 通过后应返回新 argon2 hash（无感升级）。"""
    plain = "legacy-bcrypt-pwd"
    bcrypt_only = PasswordHash((BcryptHasher(),))
    bcrypt_hashed = bcrypt_only.hash(plain)
    assert bcrypt_hashed.startswith("$2b$") or bcrypt_hashed.startswith("$2a$")

    ok, new_hash = verify_password(plain, bcrypt_hashed)
    assert ok is True
    assert new_hash is not None, "should return an argon2 hash for legacy bcrypt"
    assert new_hash.startswith("$argon2")

    ok2, _ = verify_password(plain, new_hash)
    assert ok2 is True


def test_create_and_decode_access_token_roundtrip() -> None:
    """create_access_token + decode_access_token 应能 round-trip 出 sub。"""
    user_id = "uid-abc-123"
    token = create_access_token(user_id)
    sub = decode_access_token(token)
    assert sub == user_id


def test_decode_access_token_rejects_expired() -> None:
    """已过期的 token decode 应抛 InvalidTokenError。"""
    user_id = "uid-expired"
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-60))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_tampered_signature() -> None:
    """篡改 secret_key 签发的 token 应被 decode 拒绝。"""
    bad_token = jwt.encode(
        {"sub": "evil", "exp": 9999999999},
        "this-is-not-the-real-secret",
        algorithm=ALGORITHM,
    )
    assert bad_token != ""
    with pytest.raises(InvalidTokenError):
        decode_access_token(bad_token)


def test_decode_access_token_rejects_missing_sub() -> None:
    """缺失 sub claim 的 token 应被拒绝（防止匿名 token 误打）。"""
    no_sub = jwt.encode(
        {"exp": 9999999999},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(no_sub)
