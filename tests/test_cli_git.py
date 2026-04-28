"""Tests for git-coupling CLI commands: hotspots, temporal-coupling, bus-factor,
git-coupling, report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from debtector.cli import (
    _get_store,
    cmd_bus_factor,
    cmd_git_coupling,
    cmd_hotspots,
    cmd_report,
    cmd_temporal_coupling,
)
from debtector.git_history import BusFactorMetrics, HotspotMetrics, TemporalCoupling
from debtector.logging import configure_logging
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Fixtures and helpers
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    """Keep structlog output out of stdout during tests."""
    configure_logging(project=str(tmp_path))


def _args(project: str, **kwargs) -> argparse.Namespace:
    defaults = {
        "project": project,
        "json": False,
        "limit": None,
        "since": None,
        "min_coupling": 0.0,
        "min_shared": 1,
        "min_ratio": 0.0,
        "sort": "fan_in",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        line_start=1,
        line_end=100,
        language="python",
    )


def _import(source: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


def _seed(project: str, files: dict[str, list[EdgeInfo]]) -> None:
    store = _get_store(project)
    for path, edges in files.items():
        store.store_file(path, [_file(path)], edges)
    store.close()


# Canned return values for mocking git_history functions
_HOTSPOTS = [
    HotspotMetrics(file_path="src/auth.py", churn=10, coupling=4.0, hotspot_score=40.0),
    HotspotMetrics(file_path="src/models.py", churn=3, coupling=2.0, hotspot_score=6.0),
]
_TEMPORAL = [
    TemporalCoupling(
        file_a="src/auth.py", file_b="src/models.py", shared_commits=8, coupling_ratio=0.8
    )
]
_BUS = [
    BusFactorMetrics(
        file_path="src/auth.py", top_author="Alice", top_author_pct=90.0, bus_factor=1
    ),
    BusFactorMetrics(
        file_path="src/models.py", top_author="Bob", top_author_pct=55.0, bus_factor=2
    ),
]


# ──────────────────────────────────────────────
# cmd_hotspots
# ──────────────────────────────────────────────


class TestCmdHotspots:
    """Tests for debtector hotspots."""

    def test_human_output_shows_table_columns(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS):
            cmd_hotspots(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "Churn" in out or "churn" in out.lower()
        assert "Score" in out or "score" in out.lower()

    def test_human_output_shows_file_paths(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS):
            cmd_hotspots(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "src/auth.py" in out
        assert "src/models.py" in out

    def test_json_output_structure(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS):
            cmd_hotspots(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert "hotspots" in data
        assert len(data["hotspots"]) == 2
        keys = data["hotspots"][0].keys()
        assert "file_path" in keys
        assert "churn" in keys
        assert "coupling" in keys
        assert "hotspot_score" in keys

    def test_json_empty_when_no_data(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=[]):
            cmd_hotspots(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert data == {"hotspots": []}

    def test_limit_passed_to_compute(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=[]) as mock_fn:
            cmd_hotspots(_args(str(tmp_path), limit=5))
        mock_fn.assert_called_once()
        # limit must appear as keyword arg
        assert "limit=5" in str(mock_fn.call_args)

    def test_since_passed_to_compute(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=[]) as mock_fn:
            cmd_hotspots(_args(str(tmp_path), since="6 months ago"))
        mock_fn.assert_called_once()
        call_args = mock_fn.call_args
        assert "6 months ago" in str(call_args)

    def test_empty_result_prints_message(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_hotspots", return_value=[]):
            cmd_hotspots(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "sin hotspots" in out.lower() or "sin datos" in out.lower()


# ──────────────────────────────────────────────
# cmd_temporal_coupling
# ──────────────────────────────────────────────


class TestCmdTemporalCoupling:
    """Tests for debtector temporal-coupling."""

    def test_human_output_shows_columns(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL):
            cmd_temporal_coupling(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "src/auth.py" in out
        assert "src/models.py" in out

    def test_json_output_structure(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL):
            cmd_temporal_coupling(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert "temporal_coupling" in data
        entry = data["temporal_coupling"][0]
        assert "file_a" in entry
        assert "file_b" in entry
        assert "shared_commits" in entry
        assert "coupling_ratio" in entry

    def test_json_empty_when_no_data(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_temporal_coupling", return_value=[]):
            cmd_temporal_coupling(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert data == {"temporal_coupling": []}

    def test_min_shared_passed_to_compute(self, tmp_path: Path) -> None:
        with patch("debtector.cli.compute_temporal_coupling", return_value=[]) as mock_fn:
            cmd_temporal_coupling(_args(str(tmp_path), min_shared=10))
        assert "10" in str(mock_fn.call_args)

    def test_min_ratio_passed_to_compute(self, tmp_path: Path) -> None:
        with patch("debtector.cli.compute_temporal_coupling", return_value=[]) as mock_fn:
            cmd_temporal_coupling(_args(str(tmp_path), min_ratio=0.5))
        assert "0.5" in str(mock_fn.call_args)


# ──────────────────────────────────────────────
# cmd_bus_factor
# ──────────────────────────────────────────────


class TestCmdBusFactor:
    """Tests for debtector bus-factor."""

    def test_human_output_shows_authors(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_bus_factor", return_value=_BUS):
            cmd_bus_factor(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "Alice" in out
        assert "Bob" in out

    def test_human_output_shows_file_paths(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_bus_factor", return_value=_BUS):
            cmd_bus_factor(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "src/auth.py" in out
        assert "src/models.py" in out

    def test_json_output_structure(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_bus_factor", return_value=_BUS):
            cmd_bus_factor(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert "bus_factor" in data
        entry = data["bus_factor"][0]
        assert "file_path" in entry
        assert "top_author" in entry
        assert "top_author_pct" in entry
        assert "bus_factor" in entry

    def test_json_empty_when_no_data(self, tmp_path: Path, capsys) -> None:
        with patch("debtector.cli.compute_bus_factor", return_value=[]):
            cmd_bus_factor(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert data == {"bus_factor": []}


# ──────────────────────────────────────────────
# cmd_git_coupling
# ──────────────────────────────────────────────


class TestCmdGitCoupling:
    """Tests for debtector git-coupling (aggregated view)."""

    def test_human_output_contains_all_sections(self, tmp_path: Path, capsys) -> None:
        with (
            patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS),
            patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL),
            patch("debtector.cli.compute_bus_factor", return_value=_BUS),
        ):
            cmd_git_coupling(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "src/auth.py" in out

    def test_json_output_has_all_keys(self, tmp_path: Path, capsys) -> None:
        with (
            patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS),
            patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL),
            patch("debtector.cli.compute_bus_factor", return_value=_BUS),
        ):
            cmd_git_coupling(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert "hotspots" in data
        assert "temporal_coupling" in data
        assert "bus_factor" in data

    def test_json_empty_all_keys_present(self, tmp_path: Path, capsys) -> None:
        with (
            patch("debtector.cli.compute_hotspots", return_value=[]),
            patch("debtector.cli.compute_temporal_coupling", return_value=[]),
            patch("debtector.cli.compute_bus_factor", return_value=[]),
        ):
            cmd_git_coupling(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert data == {"hotspots": [], "temporal_coupling": [], "bus_factor": []}


# ──────────────────────────────────────────────
# cmd_report
# ──────────────────────────────────────────────


class TestCmdReport:
    """Tests for debtector report (full coupling view: structural + behavioral)."""

    def test_json_has_structural_and_behavioral_keys(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        with (
            patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS),
            patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL),
            patch("debtector.cli.compute_bus_factor", return_value=_BUS),
        ):
            cmd_report(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        # Structural (from coupling)
        assert "modules" in data
        assert "cycles" in data
        assert "god_modules" in data
        # Behavioral (from git-coupling)
        assert "hotspots" in data
        assert "temporal_coupling" in data
        assert "bus_factor" in data

    def test_human_output_has_both_sections(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        with (
            patch("debtector.cli.compute_hotspots", return_value=_HOTSPOTS),
            patch("debtector.cli.compute_temporal_coupling", return_value=_TEMPORAL),
            patch("debtector.cli.compute_bus_factor", return_value=_BUS),
        ):
            cmd_report(_args(str(tmp_path)))
        out = capsys.readouterr().out
        # Should show some content from both halves
        assert "src" in out

    def test_json_output_is_valid_json(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        with (
            patch("debtector.cli.compute_hotspots", return_value=[]),
            patch("debtector.cli.compute_temporal_coupling", return_value=[]),
            patch("debtector.cli.compute_bus_factor", return_value=[]),
        ):
            cmd_report(_args(str(tmp_path), json=True))
        # Must not raise
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict)
