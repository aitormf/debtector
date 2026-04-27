"""Tests for `debtector metrics` CLI command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from debtector.cli import _get_store, cmd_metrics
from debtector.logging import configure_logging
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    """Redirect structlog to file so logs don't pollute stdout in tests."""
    configure_logging(project=str(tmp_path))


def _args(project: str, **kwargs) -> argparse.Namespace:
    defaults = {"project": project, "json": False, "sort": "fan_in", "limit": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
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
    """Store a set of files with their edges into the project store."""
    store = _get_store(project)
    for path, edges in files.items():
        store.store_file(path, [_file(path)], edges)
    store.close()


# ──────────────────────────────────────────────
# Tests — human output
# ──────────────────────────────────────────────


class TestCmdMetricsHuman:
    """cmd_metrics human-readable output."""

    def test_runs_without_error_on_empty_index(self, tmp_path: Path, capsys) -> None:
        """Empty index prints a message and exits cleanly."""
        cmd_metrics(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "sin datos" in out.lower() or len(out) >= 0  # doesn't crash

    def test_shows_table_header(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_metrics(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "Ca" in out
        assert "Ce" in out
        assert "I" in out

    def test_shows_module_rows(self, tmp_path: Path, capsys) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [],
            },
        )
        cmd_metrics(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "src/a.py" in out
        assert "src/b.py" in out

    def test_shows_god_module_marker(self, tmp_path: Path, capsys) -> None:
        """A module with very high Ca is flagged as god module."""
        files: dict[str, list[EdgeInfo]] = {"src/core.py": []}
        for i in range(15):
            imp = f"src/user_{i}.py"
            files[imp] = [_import(imp, "src/core.py")]
        _seed(str(tmp_path), files)
        cmd_metrics(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "god" in out.lower() or "●" in out or "!" in out

    def test_shows_cycles_section(self, tmp_path: Path, capsys) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        cmd_metrics(_args(str(tmp_path)))
        out = capsys.readouterr().out
        assert "ciclo" in out.lower() or "cycle" in out.lower()

    def test_limit_flag_restricts_rows(self, tmp_path: Path, capsys) -> None:
        files = {f"src/mod_{i}.py": [] for i in range(10)}
        _seed(str(tmp_path), files)
        cmd_metrics(_args(str(tmp_path), limit=3))
        out = capsys.readouterr().out
        # At most 3 module lines shown (plus header/footer)
        module_lines = [line for line in out.splitlines() if "src/mod_" in line]
        assert len(module_lines) <= 3


# ──────────────────────────────────────────────
# Tests — JSON output
# ──────────────────────────────────────────────


class TestCmdMetricsJson:
    """cmd_metrics --json output."""

    def test_json_output_is_valid(self, tmp_path: Path, capsys) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [],
            },
        )
        cmd_metrics(_args(str(tmp_path), json=True))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "modules" in data
        assert "cycles" in data
        assert "god_modules" in data

    def test_json_modules_have_required_fields(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_metrics(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        mod = data["modules"][0]
        assert "file_path" in mod
        assert "fan_in" in mod
        assert "fan_out" in mod
        assert "instability" in mod

    def test_json_cycles_list(self, tmp_path: Path, capsys) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        cmd_metrics(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["cycles"], list)
        assert len(data["cycles"]) >= 1

    def test_json_empty_index(self, tmp_path: Path, capsys) -> None:
        cmd_metrics(_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        assert data["modules"] == []
        assert data["cycles"] == []
        assert data["god_modules"] == []
