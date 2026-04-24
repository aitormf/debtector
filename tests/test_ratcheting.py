"""Tests for ratcheting CI — exit codes from `codeindex baseline status`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from codeindex.cli import _get_store, cmd_baseline
from codeindex.logging import configure_logging
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


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


class TestRatcheting:
    """baseline status exits 1 on regression, 0 on clean."""

    def test_no_regression_exits_zero(self, tmp_path: Path) -> None:
        """No changes since baseline → exit code 0."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        # Status with no changes must not raise SystemExit(1)
        cmd_baseline(_args(str(tmp_path), "status"))  # should not raise

    def test_new_cycle_exits_one(self, tmp_path: Path) -> None:
        """A new import cycle introduced after baseline → exit code 1."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

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

    def test_instability_regression_exits_one(self, tmp_path: Path) -> None:
        """Instability worsening with severity=error → exit code 1."""
        # Configure instability as error so it blocks CI
        (tmp_path / "codeindex.toml").write_text(
            '[metrics.severity]\ninstability = "error"\n', encoding="utf-8"
        )
        # baseline: a has Ca=3, Ce=1 → I=0.25
        for i in range(3):
            imp = f"src/imp_{i}.py"
            _seed(str(tmp_path), {imp: [_import(imp, "src/a.py")]})
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/x.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))

        # Worsen: a now imports 6 modules → Ce=6, Ca=3 → I=0.67
        edges_a = [_import("src/a.py", f"src/dep_{i}.py") for i in range(6)]
        _seed(str(tmp_path), {"src/a.py": edges_a})
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_args(str(tmp_path), "status"))
        assert exc.value.code == 1

    def test_no_baseline_exits_zero(self, tmp_path: Path) -> None:
        """Without a baseline, status reports but does not block CI."""
        _seed(str(tmp_path), {"src/a.py": []})
        # Should not raise — no baseline means silent mode
        cmd_baseline(_args(str(tmp_path), "status"))

    def test_improvement_exits_zero(self, tmp_path: Path) -> None:
        """Metrics stable or improving does not trigger failure.

        Scenario: baseline has a module with high fan_out; current state
        has the same or lower fan_out → no regression, exit 0.
        """
        # Seed baseline: a imports b and c
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py"), _import("src/a.py", "src/c.py")],
                "src/b.py": [],
                "src/c.py": [],
            },
        )
        cmd_baseline(_args(str(tmp_path), "save"))

        # Re-seed with identical state → no regression
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py"), _import("src/a.py", "src/c.py")],
                "src/b.py": [],
                "src/c.py": [],
            },
        )
        cmd_baseline(_args(str(tmp_path), "status"))  # should not raise

    def test_json_regression_still_exits_one(self, tmp_path: Path) -> None:
        """--json output does not suppress the exit code on regression."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_args(str(tmp_path), "status", json=True))
        assert exc.value.code == 1
