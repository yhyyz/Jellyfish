"""应用配置，从环境变量加载。"""

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Jellyfish API"
    debug: bool = False

    # API
    api_v1_prefix: str = "/api/v1"

    # Authentication (Phase 1: static API Key; empty = no auth)
    api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./jellyfish.db"

    # Redis / Celery Broker
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    celery_broker_url: str | None = None

    # CORS：环境变量中建议使用逗号分隔（更贴近 docker-compose 用法）
    # 也兼容 JSON 数组：'["http://a","http://b"]'
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        s = (self.cors_origins or "").strip()
        if not s:
            return []
        if s.startswith("["):
            loaded = json.loads(s)
            if isinstance(loaded, list):
                return [str(x).strip() for x in loaded if str(x).strip()]
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    # S3 / 对象存储（用于素材文件）
    s3_endpoint_url: str | None = None
    s3_region_name: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_name: str | None = None
    # 可选：统一前缀，方便按环境/项目隔离，如 "jellyfish/dev"
    s3_base_path: str = ""
    # 可选：对外访问基址（CDN 或自定义域名），为空则使用 S3 自带 URL 或预签名 URL
    s3_public_base_url: str | None = None

    # SMTP（W26-T1：合规 BLOCKER 告警 email 通道）
    # SMTP_HOST/PORT 缺省时 email 渠道会直接判失败（仅 Slack 投递）；
    # SMTP_USE_TLS / SMTP_START_TLS 互斥：直连 TLS（465）vs STARTTLS（587）。
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    smtp_start_tls: bool = True
    smtp_sender: str | None = None

    # ESCALATION_OWNER_EMAIL（W26-T2：团队级 BLOCKER 升级 owner 通知地址）
    # 缺省为空 → 升级判定仍会正常计数，但不发 owner 邮件（无 RBAC / User 表，
    # 因此用环境变量做唯一 fallback）。
    escalation_owner_email: str | None = None

    # DINOv2 sidecar（W27-T1：视觉一致性引擎，DECISION D-VISION-DEPLOY=sidecar）
    # base_url 缺省指向 docker-compose 内部 DNS；本机调试可在 .env 覆盖。
    # timeout 与 retries 的乘积（5×3=15s）小于 worker 默认 600s，避免单帧
    # 推理失败把整个 task 拖死。
    dinov2_sidecar_base_url: str = "http://inference-dinov2:8001"
    dinov2_sidecar_timeout_s: float = 30.0
    dinov2_sidecar_retries: int = 3
    dinov2_sidecar_retry_backoff_s: float = 1.5

    # chapter_av_export 一致性前置门绕过开关（W27-T4）
    # 默认 OFF：所有消耗 shots 的 ``consistency_status`` 必须 ≥ warning，否则
    # 入队/启动阶段直接 422 阻塞，提示先把 fail 的 shot 重生。
    # 设为 True（env: CHAPTER_AV_EXPORT_BYPASS_CONSISTENCY=1）后跳过该前置门，
    # 仅供应急 / 排障 / power-user 强制导出使用，不应作为长期配置。
    chapter_av_export_bypass_consistency: bool = False

    # === P5 W32 RBAC / JWT 配置 ===
    # 生产部署必须把 ``SECRET_KEY`` 改成 32+ 字节随机串，否则签名易被重放。
    # ``ACCESS_TOKEN_EXPIRE_MINUTES`` 控制 access token 生命周期；当前不引入
    # refresh token，60 分钟既能避免短会话刷新焦虑，又能在密钥泄露时及时缩窗。
    secret_key: str = "change-me-in-production-please-use-a-random-32byte-key"
    access_token_expire_minutes: int = 60
    # Stage-1 双轨开关（W32 过渡期）：``True`` 时仍允许调用方用旧的
    # ``api_key`` 静态 token 当 admin 通过 ``Authorization: Bearer <api_key>``。
    # 计划 ≤ 2 周后默认 ``False``，并在 P6+ 阶段彻底删除该 fallback 分支。
    jwt_fallback_to_static: bool = True
    # ``bootstrap_admin`` 启动期幂等创建首个 admin 用户（仅当 users 表为空）。
    # 生产 .env 必须改 ``BOOTSTRAP_ADMIN_PASSWORD``，否则在公网暴露 ``admin /
    # changeme`` 是即时入侵入口。
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_email: str = "admin@jellyfish.local"
    bootstrap_admin_password: str = "changeme"

    def model_post_init(self, __context: object) -> None:
        if not self.celery_broker_url or not str(self.celery_broker_url).strip():
            password_part = f":{self.redis_password}@" if self.redis_password else ""
            self.celery_broker_url = f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
