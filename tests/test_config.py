"""Tests for debtector.config — debtector.toml loading and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.config import (
    DebtectorConfig,
    MetricsSeverity,
    MetricsThresholds,
    Severity,
    load_config,
)


class TestDefaults:
    """load_config() returns sensible defaults when no toml file exists."""

    def test_returns_config_instance(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert isinstance(cfg, DebtectorConfig)

    def test_default_thresholds(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 90
        assert cfg.metrics.thresholds.god_module_min_ca == 10
        assert cfg.metrics.thresholds.sdp_margin == 0.1
        assert cfg.metrics.thresholds.max_inheritance_depth == 5
        assert cfg.metrics.thresholds.max_children == 10

    def test_default_severity(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg.metrics.severity.cycles == Severity.ERROR
        assert cfg.metrics.severity.god_modules == Severity.WARNING
        assert cfg.metrics.severity.instability == Severity.WARNING
        assert cfg.metrics.severity.inheritance == Severity.INFO


class TestTomlLoading:
    """load_config() reads values from debtector.toml when present."""

    def _write_toml(self, tmp_path: Path, content: str) -> None:
        (tmp_path / "debtector.toml").write_text(content, encoding="utf-8")

    def test_loads_toml_file(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, "[metrics.thresholds]\ngod_module_percentile = 75\n")
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 75

    def test_partial_override_keeps_defaults(self, tmp_path: Path) -> None:
        """Unspecified keys keep their default values."""
        self._write_toml(tmp_path, "[metrics.thresholds]\ngod_module_min_ca = 4\n")
        cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_min_ca == 4
        assert cfg.metrics.thresholds.god_module_percentile == 90  # default

    def test_sdp_margin_override(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, "[metrics.thresholds]\nsdp_margin = 0.3\n")
        assert load_config(tmp_path).metrics.thresholds.sdp_margin == 0.3

    @pytest.mark.parametrize(
        "line", ["god_module_min_ca = -1", 'god_module_min_ca = "x"', "sdp_margin = -0.1"]
    )
    def test_invalid_new_thresholds_raise(self, tmp_path: Path, line: str) -> None:
        self._write_toml(tmp_path, f"[metrics.thresholds]\n{line}\n")
        with pytest.raises(ValueError, match="debtector.toml"):
            load_config(tmp_path)

    def test_deprecated_instability_threshold_still_loads(self, tmp_path: Path) -> None:
        """Old configs keep working: the key is ignored and a warning is logged."""
        from structlog.testing import capture_logs

        self._write_toml(tmp_path, "[metrics.thresholds]\ninstability_threshold = 0.5\n")
        with capture_logs() as logs:
            cfg = load_config(tmp_path)
        assert cfg.metrics.thresholds.god_module_percentile == 90
        assert not hasattr(cfg.metrics.thresholds, "instability_threshold")
        assert any(e["log_level"] == "warning" and "instability_threshold" in str(e) for e in logs)

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
        (tmp_path / "debtector.toml").write_text(
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


class TestAuditThresholds:
    """``[audit.thresholds]`` in debtector.toml feeds the audit calibration."""

    def test_defaults(self, tmp_path: Path) -> None:
        thr = load_config(tmp_path).audit

        assert thr.testrisk_high_ce == 10.0
        assert thr.testrisk_high_churn == 5
        assert thr.testrisk_high_ca == 10.0
        assert thr.hotspot_percentile == 90
        assert thr.hotspot_min_score == 50

    def test_overrides_and_partial_defaults(self, tmp_path: Path) -> None:
        (tmp_path / "debtector.toml").write_text(
            "[audit.thresholds]\ntestrisk_high_churn = 8\nhotspot_percentile = 75\n"
            "hotspot_min_score = 40\n",
            encoding="utf-8",
        )

        thr = load_config(tmp_path).audit

        assert thr.testrisk_high_churn == 8
        assert thr.hotspot_percentile == 75
        assert thr.hotspot_min_score == 40
        assert thr.testrisk_high_ce == 10.0  # untouched keys keep their default

    @pytest.mark.parametrize(
        "body",
        [
            "hotspot_percentile = 0",
            "hotspot_percentile = 100",
            "hotspot_min_score = -1",
            'testrisk_high_ce = "ten"',
        ],
    )
    def test_invalid_values_raise(self, tmp_path: Path, body: str) -> None:
        (tmp_path / "debtector.toml").write_text(f"[audit.thresholds]\n{body}\n", encoding="utf-8")

        with pytest.raises(ValueError, match="audit.thresholds"):
            load_config(tmp_path)


class TestTestriskDefaultsLiveInConfig:
    """config.py owns the test-risk defaults; it does not depend on audit/testrisk.py (SDP)."""

    def test_config_does_not_import_testrisk(self) -> None:
        import ast

        import debtector.config as config_module

        tree = ast.parse(Path(config_module.__file__).read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert "audit.testrisk" not in imported

    def test_testrisk_uses_config_defaults(self) -> None:
        from debtector import config
        from debtector.audit import testrisk

        assert config.DEFAULT_HIGH_CE == testrisk.DEFAULT_HIGH_CE == 10.0
        assert config.DEFAULT_HIGH_CHURN == testrisk.DEFAULT_HIGH_CHURN == 5
        assert config.DEFAULT_HIGH_CA == testrisk.DEFAULT_HIGH_CA == 10.0
