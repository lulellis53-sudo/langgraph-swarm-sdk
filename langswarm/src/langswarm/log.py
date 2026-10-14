"""Structured logging with loguru.

Records emitted through the standard-library logging API by LangChain,
LangGraph, and uvicorn are intercepted and routed through loguru, so the
whole stack shares one sink, one format, and one JSON switch.
"""

__lazy_modules__ = ["loguru"]

import logging
import sys

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Forward standard-library records into loguru with correct depth."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = sys._getframe(1), 0
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Install loguru as the process-wide logging facade."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        serialize=json_logs,
        backtrace=True,
        diagnose=False,
    )
    handler = _InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    for name in ("langchain", "langgraph", "uvicorn", "uvicorn.access", "uvicorn.error"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [handler]
        std_logger.propagate = False
