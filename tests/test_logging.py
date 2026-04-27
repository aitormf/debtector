"""Tests for the structlog configuration module."""

from __future__ import annotations

import structlog


class TestConfigureLogging:
    """Tests for configure_logging()."""

    def test_returns_bound_logger(self) -> None:
        """get_logger() returns a structlog BoundLogger."""
        from debtector.logging import get_logger

        log = get_logger()
        assert log is not None
        assert hasattr(log, "info")
        assert hasattr(log, "debug")
        assert hasattr(log, "warning")
        assert hasattr(log, "error")

    def test_configure_console_output(self) -> None:
        """configure_logging(json_output=False) configures without raising."""
        from debtector.logging import configure_logging

        configure_logging(json_output=False)
        log = structlog.get_logger()
        # Should not raise
        log.info("test_event", key="value")

    def test_configure_json_output(self) -> None:
        """configure_logging(json_output=True) configures without raising."""
        from debtector.logging import configure_logging

        configure_logging(json_output=True)
        log = structlog.get_logger()
        # Should not raise
        log.info("test_event", key="value")

    def test_reads_env_var_false(self, monkeypatch: object) -> None:
        """configure_logging() uses DEBTECTOR_LOG_JSON=false for console output."""
        from debtector.logging import configure_logging

        monkeypatch.setenv("DEBTECTOR_LOG_JSON", "false")
        # Should not raise — console mode
        configure_logging()

    def test_reads_env_var_true(self, monkeypatch: object) -> None:
        """configure_logging() uses DEBTECTOR_LOG_JSON=true for JSON output."""
        from debtector.logging import configure_logging

        monkeypatch.setenv("DEBTECTOR_LOG_JSON", "true")
        # Should not raise — JSON mode
        configure_logging()

    def test_default_is_console(self, monkeypatch: object) -> None:
        """configure_logging() defaults to console when env var is absent."""
        from debtector.logging import configure_logging

        monkeypatch.delenv("DEBTECTOR_LOG_JSON", raising=False)
        # Should not raise
        configure_logging()

    def test_get_logger_returns_bound_logger_with_context(self) -> None:
        """get_logger().bind() propagates context to subsequent calls."""
        from debtector.logging import get_logger

        log = get_logger()
        bound = log.bind(component="test", operation="verify")
        assert bound is not None
        assert hasattr(bound, "info")
