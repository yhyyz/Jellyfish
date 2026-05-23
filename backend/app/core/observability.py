"""可观测性配置：Prometheus 指标 + structlog 结构化日志。

提供应用级别的指标采集和结构化日志初始化，
使后端具备生产环境所需的可观测性基础设施。
"""

import logging
import os
import sys

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app: FastAPI) -> None:
    """初始化 Prometheus 指标采集并暴露 /metrics 端点。

    使用 prometheus-fastapi-instrumentator 自动采集 HTTP 请求指标，
    包括请求计数、延迟分布、响应大小等。

    Args:
        app: FastAPI 应用实例。
    """
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def setup_logging() -> None:
    """初始化 structlog 结构化日志。

    根据环境变量 ENV 决定输出格式：
    - production / staging: JSON 格式，便于日志聚合系统解析。
    - 其他（开发环境）: 彩色控制台格式，便于本地调试。
    """
    env = os.getenv("ENV", "development").lower()
    is_prod = env in ("production", "staging")

    # 共享处理器链
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_prod:
        # 生产环境：JSON 输出
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # 开发环境：彩色控制台输出
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging 使用 structlog 格式化
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
