"""
Structured logging configuration using structlog.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.typing import Processor


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    
    # Set up standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    
    # Configure structlog processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    
    # Development: colored console output
    # Production: JSON output
    if sys.stderr.isatty():
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    else:
        processors = shared_processors + [
            structlog.processors.dict_tramp,
            structlog.processors.JSONRenderer()
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance with optional name binding."""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(module=name)
    return logger


class LoggerMixin:
    """Mixin class to add logging to any class."""
    
    @property
    def log(self) -> structlog.BoundLogger:
        """Get a logger bound to this class name."""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger


def log_context(**kwargs: Any) -> structlog.contextvars.bound_contextvars:
    """Context manager to add context to all log messages in scope."""
    return structlog.contextvars.bound_contextvars(**kwargs)
