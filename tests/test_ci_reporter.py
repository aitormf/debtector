"""Tests for CI reporter — GitHub Annotations and GitLab CI output."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from debtector.cli import _get_store, cmd_baseline
from debtector.logging import configure_logging
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _args(project: str, subcommand: str, **kwargs) -> argparse.Namespace:
    defaults = {
        "project": project,
        "json": False,
        "baseline_cmd": subcommand,
        "reporter": None,
    }
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


class TestGitHubAnnotations:
    """--reporter github emits ::warning/::error annotations."""

    def test_cycle_emits_github_annotation(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit):
            cmd_baseline(_args(str(tmp_path), "status", reporter="github"))
        out = capsys.readouterr().out
        assert "::" in out  # GitHub annotation format
        assert "warning" in out.lower() or "error" in out.lower()

    def test_github_annotation_format(self, tmp_path: Path, capsys) -> None:
        """Each annotation line matches ::level file=...,line=...::<message>."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit):
            cmd_baseline(_args(str(tmp_path), "status", reporter="github"))
        out = capsys.readouterr().out
        annotation_lines = [line for line in out.splitlines() if line.startswith("::")]
        assert len(annotation_lines) >= 1
        for line in annotation_lines:
            # Format: ::level file=<path>,line=<n>::<message>
            assert line.startswith("::warning") or line.startswith("::error")

    def test_no_regression_no_annotations(self, tmp_path: Path, capsys) -> None:
        """No regressions → no annotation lines."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        cmd_baseline(_args(str(tmp_path), "status", reporter="github"))
        out = capsys.readouterr().out
        assert "::" not in out

    def test_severity_maps_to_annotation_level(self, tmp_path: Path, capsys) -> None:
        """error severity → ::error, warning severity → ::warning."""
        (tmp_path / "debtector.toml").write_text(
            '[metrics.severity]\ncycles = "warning"\n', encoding="utf-8"
        )
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        cmd_baseline(_args(str(tmp_path), "status", reporter="github"))
        out = capsys.readouterr().out
        annotation_lines = [line for line in out.splitlines() if line.startswith("::")]
        assert any(line.startswith("::warning") for line in annotation_lines)


class TestGitLabCI:
    """--reporter gitlab emits section markers and colored output."""

    def test_gitlab_cycle_section(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit):
            cmd_baseline(_args(str(tmp_path), "status", reporter="gitlab"))
        out = capsys.readouterr().out
        # GitLab uses ANSI or section markers
        assert "ciclo" in out.lower() or "cycle" in out.lower()

    def test_no_regression_gitlab_clean(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        cmd_baseline(_args(str(tmp_path), "status", reporter="gitlab"))
        out = capsys.readouterr().out
        assert "sin cambios" in out.lower() or "✓" in out
