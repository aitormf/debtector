"""Structured logging configuration for Debtector using structlog.

Usage:
    from debtector.logging import configure_logging, get_logger

    configure_logging(project=".")  # call once after arg parse
    log = get_logger()
    log = log.bind(file_path="src/app.py", operation="index")
    log.info("indexing_started")

Environment:
    DEBTECTOR_LOG_JSON=false  → human-readable log lines (default)
    DEBTECTOR_LOG_JSON=true   → JSON lines
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import structlog


def configure_logging(project: str = ".", json_output: bool | None = None) -> None:
    """Configure structlog to write to ``.debtector/debtector.log`` inside *project*.

    Creates the ``.debtector/`` directory if it does not exist.  Falls back to
    ``stderr`` if the log file cannot be opened (e.g. read-only filesystem).

    Should be called once at application startup, after argument parsing so
    that the correct *project* path is known.

    Args:
        project: Path to the project root.  Logs are written to
            ``{project}/.debtector/debtector.log``.  Defaults to the current
            working directory.
        json_output: ``True`` for JSON lines, ``False`` for human-readable
            lines.  When ``None``, reads the ``DEBTECTOR_LOG_JSON`` environment
            variable (defaults to ``False`` when absent).
    """
    if json_output is None:
        env_val = os.environ.get("DEBTECTOR_LOG_JSON", "false").strip().lower()
        json_output = env_val == "true"

    # Resolve log file path
    log_file = _open_log_file(project)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_file),
        cache_logger_on_first_use=False,
    )


def _open_log_file(project: str):
    """Open (or create) the log file, falling back to stderr on error.

    Args:
        project: Path to the project root directory.

    Returns:
        A writable file-like object.
    """
    try:
        debtector_dir = Path(project) / ".debtector"
        debtector_dir.mkdir(parents=True, exist_ok=True)
        log_path = debtector_dir / "debtector.log"
        return open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    except OSError:
        return sys.stderr


def get_logger() -> structlog.BoundLogger:
    """Return a structlog BoundLogger instance.

    Returns:
        A structlog BoundLogger ready to use with ``.bind()`` and log methods.
    """
    return structlog.get_logger()
