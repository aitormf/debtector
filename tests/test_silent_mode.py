"""Tests for silent mode — without baseline, codeindex never fails CI."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from codeindex.cli import _get_store, cmd_baseline, cmd_metrics
from codeindex.logging import configure_logging
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _args_metrics(project: str, **kwargs) -> argparse.Namespace:
    defaults = {"project": project, "json": False, "sort": "fan_in", "limit": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _args_baseline(project: str, subcommand: str, **kwargs) -> argparse.Namespace:
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


class TestSilentMode:
    """Without baseline, no command exits with code 1."""

    def test_metrics_never_exits_one(self, tmp_path: Path) -> None:
        """codeindex metrics always exits 0 — it only reports, never blocks."""
        # Even with cycles and high Ca, metrics command must not raise SystemExit
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],  # cycle
            },
        )
        cmd_metrics(_args_metrics(str(tmp_path)))  # must not raise

    def test_baseline_status_without_baseline_exits_zero(self, tmp_path: Path) -> None:
        """baseline status with no saved baseline exits 0 (first run)."""
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        # No baseline saved → must not raise
        cmd_baseline(_args_baseline(str(tmp_path), "status"))

    def test_baseline_status_without_baseline_json_exits_zero(self, tmp_path: Path, capsys) -> None:
        """baseline status --json with no baseline exits 0."""
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args_baseline(str(tmp_path), "status", json=True))
        import json

        data = json.loads(capsys.readouterr().out)
        assert "error" in data  # informs about missing baseline

    def test_first_save_then_status_clean_exits_zero(self, tmp_path: Path) -> None:
        """First save + immediate status (no changes) exits 0."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args_baseline(str(tmp_path), "save"))
        cmd_baseline(_args_baseline(str(tmp_path), "status"))  # must not raise

    def test_metrics_json_never_exits_one(self, tmp_path: Path, capsys) -> None:
        """codeindex metrics --json also never exits 1."""
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        cmd_metrics(_args_metrics(str(tmp_path), json=True))  # must not raise
        import json

        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["cycles"], list)
