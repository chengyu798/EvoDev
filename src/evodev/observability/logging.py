"""配置面向终端用户的结构化日志。"""

import logging
import sys
from typing import Any

import structlog

LEVEL_LABELS = {
    "debug": "调试",
    "info": "进度",
    "warning": "警告",
    "error": "错误",
    "critical": "严重错误",
}


def render_console_log(
    _: object,
    method_name: str,
    event_dict: dict[str, Any],
) -> str:
    """把结构化事件渲染为紧凑的中文终端日志。"""
    timestamp = event_dict.pop("timestamp", "")
    level = event_dict.pop("level", method_name)
    event = event_dict.pop("event", "")
    fields = " ".join(f"{key}={value}" for key, value in event_dict.items())
    suffix = f" {fields}" if fields else ""
    return f"{timestamp} [{LEVEL_LABELS.get(level, level)}] {event}{suffix}"


def configure_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """根据 CLI 模式配置日志级别和控制台样式。"""
    if quiet:
        level = logging.CRITICAL
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
            render_console_log,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
