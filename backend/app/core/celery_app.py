"""Celery 应用实例。

最小落地原则：
- 仅把 Celery 当作执行层与 broker 客户端；
- 任务状态/结果真相仍然回写 GenerationTask；
- 第一阶段不依赖 Celery result backend。
"""

from celery import Celery
from celery.signals import worker_process_init

from app.config import settings
from app.core.db import reset_db_runtime


celery_app = Celery(
    "jellyfish",
    broker=settings.celery_broker_url,
    include=["app.tasks.execute_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 任务队列路由：根据 Celery 已注册任务名 (`task.execute*` 命名空间) 路由。
    #
    # 项目实际只在 `app.tasks.execute_task` 中注册了一个统一执行入口
    # `@celery_app.task(name="task.execute")`，所以路由必须以 `task.execute*`
    # 为锚点，而不是按模块路径 `app.services.worker.*` 匹配（旧规则永远命不中）。
    #
    # 约定：
    # - `task.execute.video` / `task.execute.image` / `task.execute.timeline`
    #   等耗时任务入口落到 `slow` 队列；
    # - 其余 `task.execute*`（含当前默认入口 `task.execute`）落到 `fast` 队列。
    # Celery 路由按声明顺序匹配，先列具体规则再列兜底。
    task_routes={
        "task.execute.video*": {"queue": "slow"},
        "task.execute.image*": {"queue": "slow"},
        "task.execute.timeline*": {"queue": "slow"},
        "task.execute*": {"queue": "fast"},
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
