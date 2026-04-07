"""Structured logging configuration for CodeIndex using structlog.

Usage:
    from codeindex.logging import configure_logging, get_logger

    configure_logging()  # call once at startup (reads CODEINDEX_LOG_JSON)
    log = get_logger()
    log = log.bind(file_path="src/app.py", operation="index")
    log.info("indexing_started")

Environment:
    CODEINDEX_LOG_JSON=false  → colored console output (default, dev)
    CODEINDEX_LOG_JSON=true   → JSON lines output (prod)
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(json_output: bool | None = None) -> None:
    """Configure structlog for the application.

    Reads CODEINDEX_LOG_JSON from the environment when json_output is None.
    Should be called once at application startup (e.g., in cli.main()).

    Args:
        json_output: True for JSON lines (prod), False for colored console (dev).
            When None, reads the CODEINDEX_LOG_JSON environment variable.
            Defaults to False (console) when the variable is absent.
    """
    if json_output is None:
        env_val = os.environ.get("CODEINDEX_LOG_JSON", "false").strip().lower()
        json_output = env_val == "true"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.BoundLogger:
    """Return a structlog BoundLogger instance.

    Returns:
        A structlog BoundLogger ready to use with .bind() and log methods.
    """
    return structlog.get_logger()
