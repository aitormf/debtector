"""Tests for codeindex.config — codeindex.toml loading and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.config import (
    CodeIndexConfig,
    MetricsSeverity,
    MetricsThresholds,
    Severity,
    load_config,
)


class TestDefaults:
    """load_config() returns sensible defaults when no toml file exists."""

    def test_returns_config_instance(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert isinstance(cfg, CodeIndexConfig)

    def test_default_thresholds(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 90
        assert cfg.metrics.thresholds.instability_threshold == 0.8
        assert cfg.metrics.thresholds.max_inheritance_depth == 5
        assert cfg.metrics.thresholds.max_children == 10

    def test_default_severity(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg.metrics.severity.cycles == Severity.ERROR
        assert cfg.metrics.severity.god_modules == Severity.WARNING
        assert cfg.metrics.severity.instability == Severity.WARNING
        assert cfg.metrics.severity.inheritance == Severity.INFO


class TestTomlLoading:
    """load_config() reads values from codeindex.toml when present."""

    def _write_toml(self, tmp_path: Path, content: str) -> None:
        (tmp_path / "codeindex.toml").write_text(content, encoding="utf-8")

    def test_loads_toml_file(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, "[metrics.thresholds]\ngod_module_percentile = 75\n")
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 75

    def test_partial_override_keeps_defaults(self, tmp_path: Path) -> None:
        """Unspecified keys keep their default values."""
        self._write_toml(tmp_path, "[metrics.thresholds]\ninstability_threshold = 0.5\n")
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.instability_threshold == 0.5
        assert cfg.metrics.thresholds.god_module_percentile == 90  # default

    def test_severity_override(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, '[metrics.severity]\ncycles = "warning"\n')
        cfg = load_config(tmp_path)
        assert cfg.metrics.severity.cycles == Severity.WARNING

    def test_full_config(self, tmp_path: Path) -> None:
        toml = """\
[metrics.thresholds]
god_module_percentile = 95
instability_threshold = 0.9
max_inheritance_depth = 3
max_children = 5

[metrics.severity]
cycles      = "error"
god_modules = "error"
instability = "warning"
inheritance = "info"
"""
        self._write_toml(tmp_path, toml)
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 95
        assert cfg.metrics.thresholds.max_children == 5
        assert cfg.metrics.severity.god_modules == Severity.ERROR

    def test_accepts_path_or_string(self, tmp_path: Path) -> None:
        """load_config accepts both Path and str as project root."""
        self._write_toml(tmp_path, "[metrics.thresholds]\nmax_children = 7\n")
        cfg_path = load_config(tmp_path)
        cfg_str = load_config(str(tmp_path))
        assert cfg_path.metrics.thresholds.max_children == 7
        assert cfg_str.metrics.thresholds.max_children == 7


class TestSeverityEnum:
    """Severity enum values and string coercion."""

    def test_severity_values(self) -> None:
        assert Severity.ERROR == "error"
        assert Severity.WARNING == "warning"
        assert Severity.INFO == "info"

    def test_invalid_severity_raises(self, tmp_path: Path) -> None:
        (tmp_path / "codeindex.toml").write_text(
            '[metrics.severity]\ncycles = "critical"\n', encoding="utf-8"
        )
        with pytest.raises((ValueError, KeyError)):
            load_config(tmp_path)


class TestConfigDataclasses:
    """MetricsThresholds and MetricsSeverity are proper dataclasses."""

    def test_thresholds_dataclass(self) -> None:
        t = MetricsThresholds()
        assert hasattr(t, "god_module_percentile")

    def test_severity_dataclass(self) -> None:
        s = MetricsSeverity()
        assert hasattr(s, "cycles")
