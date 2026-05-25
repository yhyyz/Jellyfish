"""Celery 任务路由解析测试。

校验 `app.core.celery_app.celery_app` 的 `task_routes` 配置能将
`task.execute*` 命名空间下的注册任务名正确路由到 `fast` / `slow` 队列。

这个测试是为了防止再次出现历史问题：旧规则使用 `app.services.worker.*`
glob，但项目实际注册的 Celery 任务名是 `task.execute*`，因此旧规则
永远命不中，所有任务都落到默认队列。
"""

from __future__ import annotations

import pytest

from app.core.celery_app import celery_app


@pytest.mark.parametrize(
    ("task_name", "expected_queue"),
    [
        # 当前真实注册的统一执行入口必须落到 fast 队列。
        ("task.execute", "fast"),
        # 预留的耗时任务命名空间必须落到 slow 队列。
        ("task.execute.video", "slow"),
        ("task.execute.video.dashscope", "slow"),
        ("task.execute.image", "slow"),
        ("task.execute.image.dashscope", "slow"),
        ("task.execute.timeline", "slow"),
        ("task.execute.timeline.export", "slow"),
        # 其他 task.execute* 命名走 fast 兜底。
        ("task.execute.text", "fast"),
        ("task.execute.script_divide", "fast"),
    ],
)
def test_celery_task_routes_resolve_to_expected_queue(task_name: str, expected_queue: str) -> None:
    """`celery_app.amqp.router.route` 必须按命名空间把任务路由到预期队列。"""

    route = celery_app.amqp.router.route({}, task_name)
    queue = route.get("queue")
    if queue is None and route.get("queue_name") is not None:
        queue = route["queue_name"]
    if hasattr(queue, "name"):
        queue = queue.name
    assert queue == expected_queue, f"task {task_name!r} routed to {queue!r}, expected {expected_queue!r}"


def test_celery_task_routes_do_not_use_legacy_module_path_glob() -> None:
    """回归测试：路由配置不应再依赖 `app.services.worker.*` 模块路径 glob。

    旧 glob 永远命不中已注册的 `task.execute*` 命名空间，必须确保不再回退。
    """

    routes = celery_app.conf.task_routes
    pattern_strings: list[str] = []
    if isinstance(routes, dict):
        pattern_strings.extend(str(k) for k in routes.keys())
    elif isinstance(routes, (list, tuple)):
        for item in routes:
            if isinstance(item, (list, tuple)) and item:
                pattern_strings.append(str(item[0]))
            else:
                pattern_strings.append(str(item))

    assert pattern_strings, "task_routes must be configured"
    for pat in pattern_strings:
        assert not pat.startswith("app.services.worker."), (
            f"legacy module-path glob still configured: {pat!r}"
        )
    assert any(p.startswith("task.execute") for p in pattern_strings), (
        f"task_routes must anchor on `task.execute*`, got {pattern_strings!r}"
    )
