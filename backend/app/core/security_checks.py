"""启动期安全 sanity 检查（v0.7.1 引入）。

为什么独立成模块：
    安全相关的"启动失败 vs 启动 warning"判定逻辑零散在 ``main.py`` 里很
    容易被后续重构吞掉；专门放一份 ``app.core.security_checks`` 让这条
    红线显式可读，未来新增检查（如 SMTP 凭据、S3 凭据等）也有同一处落
    点。

做什么：
    - :func:`check_security_at_boot` 在 lifespan 启动期调用一次：
        * ``BOOTSTRAP_ADMIN_PASSWORD == 'changeme'`` →
          - production / prod / staging env 直接 ``RuntimeError`` 阻塞启动；
          - 其它环境（development / test / 缺省）打 warning，让本地开发顺畅。
        * ``SECRET_KEY`` 仍是默认占位字符串 → 同上策略。
    - 通过 ``JELLYFISH_ENV`` 环境变量识别部署环境；缺省视为
      ``development``。

为什么 staging 也要 reject：
    staging 通常对内网或测试 partner 开放，仍是攻击面；用 ``changeme`` 当
    bootstrap admin 密码会让 staging 沦为权限提升跳板。production-only
    放行不够。

为什么不直接 raise 在 :class:`Settings` 校验里：
    - Settings 一旦实例化就立即跑校验，影响 unit test 的 import 性能；
    - 单测用 ``settings.bootstrap_admin_password = 'changeme'`` 临时 mock
      会被构造期校验直接 reject，导致依赖默认值的旧测试全挂。
    把检查推到 lifespan 期才执行，让 import-time 仍然零成本。
"""

from __future__ import annotations

import logging
import os

from app.config import settings


_LOGGER = logging.getLogger(__name__)

# 与 :class:`Settings` 默认值对应的"未改"哨兵值；变更需要同步两处。
_DEFAULT_SECRET_KEY = "change-me-in-production-please-use-a-random-32byte-key"
_DEFAULT_ADMIN_PASSWORD = "changeme"

# 部署环境集合：命中其一时 sanity check 直接抛 RuntimeError。
_PRODUCTION_LIKE_ENVS: frozenset[str] = frozenset({"production", "prod", "staging"})


def _current_env() -> str:
    """读取 ``JELLYFISH_ENV`` 环境变量并归一化（小写、去空格、缺省 ``development``）。"""

    raw = os.getenv("JELLYFISH_ENV", "development")
    return (raw or "development").strip().lower()


def _is_production_like(env: str) -> bool:
    """归一化后的 env 字符串是否属于"production-like"（必须严格安全）。"""

    return env in _PRODUCTION_LIKE_ENVS


def check_security_at_boot() -> None:
    """启动期 sanity 检查：默认值在 production-like 环境下必须被显式覆盖。

    Raises:
        RuntimeError: production / prod / staging env 下检测到默认占位值。
    """

    env = _current_env()
    is_prod = _is_production_like(env)

    if settings.bootstrap_admin_password == _DEFAULT_ADMIN_PASSWORD:
        if is_prod:
            raise RuntimeError(
                "BOOTSTRAP_ADMIN_PASSWORD == 'changeme' is rejected in "
                f"production-like env (JELLYFISH_ENV={env!r}). Set a real "
                "password in .env before starting Jellyfish."
            )
        _LOGGER.warning(
            "BOOTSTRAP_ADMIN_PASSWORD is the default 'changeme'. "
            "MUST CHANGE before production deployment "
            "(JELLYFISH_ENV=%r).",
            env,
        )

    if settings.secret_key == _DEFAULT_SECRET_KEY:
        if is_prod:
            raise RuntimeError(
                "SECRET_KEY is the default placeholder which is rejected in "
                f"production-like env (JELLYFISH_ENV={env!r}). Set a "
                "32+ byte random string in .env before starting Jellyfish."
            )
        _LOGGER.warning(
            "SECRET_KEY is the default placeholder. MUST CHANGE before "
            "production deployment (JELLYFISH_ENV=%r).",
            env,
        )


__all__ = ["check_security_at_boot"]
