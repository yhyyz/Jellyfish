"""``app.services.api_quota`` namespace（P4 W24-T1）。

包含 :mod:`quota_service` 模块：API key 的 CRUD（create / list /
revoke / usage）。生成、校验与原子配额扣减发生在
:mod:`app.core.api_key_auth`，不在 service 内重复实现。
"""

from app.services.api_quota.quota_service import (
    BCRYPT_COST,
    KEY_PLAINTEXT_PREFIX,
    create_api_key,
    get_usage,
    list_api_keys,
    revoke_api_key,
)

__all__ = [
    "BCRYPT_COST",
    "KEY_PLAINTEXT_PREFIX",
    "create_api_key",
    "get_usage",
    "list_api_keys",
    "revoke_api_key",
]
