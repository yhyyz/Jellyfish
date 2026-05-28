"""Celery 应用实例。

最小落地原则：
- 仅把 Celery 当作执行层与 broker 客户端；
- 任务状态/结果真相仍然回写 GenerationTask；
- 第一阶段不依赖 Celery result backend。

W24-T4：新增 beat_schedule + redbeat scheduler 用于周期性配额重置。
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.config import settings
from app.core.db import reset_db_runtime


celery_app = Celery(
    "jellyfish",
    broker=settings.celery_broker_url,
    include=[
        "app.tasks.execute_task",
        "app.tasks.quota_reset",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_routes={
        "task.execute.video*": {"queue": "slow"},
        "task.execute.image*": {"queue": "slow"},
        "task.execute.timeline*": {"queue": "slow"},
        "task.execute*": {"queue": "fast"},
    },
    # W24-T4：周期任务调度器使用 RedBeat（基于 Redis 的分布式锁），
    # 支持多进程/多副本同时启动 beat 而不重复触发。默认的
    # ``celery.beat.PersistentScheduler`` 用本地文件存储，无法在
    # docker-compose 多副本部署下安全运行。
    beat_scheduler="redbeat.RedBeatScheduler",
    # RedBeat 复用现有 Celery broker（Redis）即可；额外允许通过
    # ``settings.celery_broker_url`` 指向独立 redis URL。
    redbeat_redis_url=settings.celery_broker_url,
    redbeat_lock_timeout=900,
    beat_schedule={
        # 每日 00:00（项目时区 Asia/Shanghai）重置 ``consumed_today``。
        "reset-daily-quotas": {
            "task": "task.quota.reset_daily",
            "schedule": crontab(minute=0, hour=0),
        },
        # 每月 1 日 00:00 重置 ``consumed_this_month``。
        "reset-monthly-quotas": {
            "task": "task.quota.reset_monthly",
            "schedule": crontab(minute=0, hour=0, day_of_month=1),
        },
    },
)


@worker_process_init.connect
def _reset_async_db_runtime(**_: object) -> None:
    """Celery prefork 子进程启动后，重建 async DB 运行时 + 注册 provider/task 别名表。

    为何同时调用 ``bootstrap_all_registries()``：
        Celery 子进程不会经过 FastAPI ``lifespan``，因此进程内的 provider
        别名表 (``_KEY_BY_ALIAS``) 与 task 适配器注册都是空的。
        ``try_resolve_provider_key_from_name`` 依赖该表，否则即使 DB 中
        存在 ``aliyun_bailian`` Provider 行也会被判定为 "Unsupported"，
        导致 worker (如 ``tts_generate_worker``) 误抛
        "requires an aliyun_bailian (DashScope) provider"。
        本地注册全部为 in-memory + 幂等，可在 prefork 子进程多次调用。
    """

    from app.bootstrap import bootstrap_all_registries

    reset_db_runtime()
    bootstrap_all_registries()
