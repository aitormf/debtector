"""Tests for `codeindex baseline save` and `codeindex baseline status`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from codeindex.cli import _get_store, cmd_baseline
from codeindex.logging import configure_logging
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _args(project: str, subcommand: str, **kwargs) -> argparse.Namespace:
    defaults = {"project": project, "json": False, "baseline_cmd": subcommand}
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
    store = _get_store(project)
    for path, edges in files.items():
        store.store_file(path, [_file(path)], edges)
    store.close()


# ──────────────────────────────────────────────
# baseline save
# ──────────────────────────────────────────────


class TestBaselineSave:
    """codeindex baseline save writes .codeindex/baseline.json."""

    def test_creates_baseline_file(self, tmp_path: Path) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        assert (tmp_path / ".codeindex" / "baseline.json").exists()

    def test_baseline_contains_required_keys(self, tmp_path: Path) -> None:
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/b.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))
        data = json.loads((tmp_path / ".codeindex" / "baseline.json").read_text())
        assert "modules" in data
        assert "cycles" in data
        assert "god_modules" in data
        assert "saved_at" in data

    def test_baseline_modules_have_metrics(self, tmp_path: Path) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [],
            },
        )
        cmd_baseline(_args(str(tmp_path), "save"))
        data = json.loads((tmp_path / ".codeindex" / "baseline.json").read_text())
        mod = next(m for m in data["modules"] if m["file_path"] == "src/a.py")
        assert mod["fan_out"] > 0
        assert "instability" in mod

    def test_save_prints_confirmation(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        out = capsys.readouterr().out
        assert "baseline" in out.lower()

    def test_save_json_output(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save", json=True))
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "saved"
        assert "path" in data

    def test_overwrites_existing_baseline(self, tmp_path: Path) -> None:
        """Running save twice updates the baseline."""
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        first = json.loads((tmp_path / ".codeindex" / "baseline.json").read_text())

        # Add a new file
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        second = json.loads((tmp_path / ".codeindex" / "baseline.json").read_text())

        assert len(second["modules"]) >= len(first["modules"])


# ──────────────────────────────────────────────
# baseline status
# ──────────────────────────────────────────────


class TestBaselineStatus:
    """codeindex baseline status compares current metrics to baseline."""

    def test_no_baseline_prints_message(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "baseline" in out.lower()

    def test_no_changes_shows_ok(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/b.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()  # clear save output

        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "sin cambios" in out.lower() or "ok" in out.lower() or "✓" in out

    def test_new_cycle_detected_as_regression(self, tmp_path: Path, capsys) -> None:
        """A cycle introduced after baseline is reported and exits 1."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()

        # Introduce cycle
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_args(str(tmp_path), "status"))
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "ciclo" in out.lower() or "cycle" in out.lower()

    def test_status_json_output(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()

        cmd_baseline(_args(str(tmp_path), "status", json=True))
        data = json.loads(capsys.readouterr().out)
        assert "regressions" in data
        assert "new_cycles" in data
        assert "new_god_modules" in data
