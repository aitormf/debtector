"""Tests for configurable severity in baseline status."""

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


def _write_toml(project: str, content: str) -> None:
    (Path(project) / "codeindex.toml").write_text(content, encoding="utf-8")


class TestSeverityError:
    """severity=error (default) blocks CI on regression."""

    def test_cycle_with_error_severity_exits_one(self, tmp_path: Path) -> None:
        _write_toml(str(tmp_path), '[metrics.severity]\ncycles = "error"\n')
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


class TestSeverityWarning:
    """severity=warning reports the issue but exits 0."""

    def test_cycle_with_warning_severity_exits_zero(self, tmp_path: Path) -> None:
        _write_toml(str(tmp_path), '[metrics.severity]\ncycles = "warning"\n')
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        # Should NOT raise — warning doesn't block
        cmd_baseline(_args(str(tmp_path), "status"))

    def test_cycle_warning_still_prints_message(self, tmp_path: Path, capsys) -> None:
        _write_toml(str(tmp_path), '[metrics.severity]\ncycles = "warning"\n')
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()

        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "ciclo" in out.lower() or "cycle" in out.lower()

    def test_instability_warning_exits_zero(self, tmp_path: Path) -> None:
        _write_toml(str(tmp_path), '[metrics.severity]\ninstability = "warning"\n')
        # Seed baseline with low instability
        for i in range(3):
            imp = f"src/imp_{i}.py"
            _seed(str(tmp_path), {imp: [_import(imp, "src/a.py")]})
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/x.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))

        # Worsen instability
        edges_a = [_import("src/a.py", f"src/dep_{i}.py") for i in range(6)]
        _seed(str(tmp_path), {"src/a.py": edges_a})
        # warning → exit 0
        cmd_baseline(_args(str(tmp_path), "status"))


class TestSeverityInfo:
    """severity=info reports minimally and always exits 0."""

    def test_cycle_info_exits_zero(self, tmp_path: Path) -> None:
        _write_toml(
            str(tmp_path),
            '[metrics.severity]\ncycles = "info"\ngod_modules = "info"\ninstability = "info"\n',
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
        cmd_baseline(_args(str(tmp_path), "status"))  # must not raise


class TestSeverityMixed:
    """Different severities per check type."""

    def test_cycles_error_instability_warning(self, tmp_path: Path) -> None:
        """Cycles=error blocks; instability=warning doesn't."""
        _write_toml(
            str(tmp_path),
            '[metrics.severity]\ncycles = "error"\ninstability = "warning"\n',
        )
        # Seed baseline with low instability
        for i in range(3):
            imp = f"src/imp_{i}.py"
            _seed(str(tmp_path), {imp: [_import(imp, "src/a.py")]})
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/x.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))

        # Only instability regression, no cycle → warning severity → exit 0
        edges_a = [_import("src/a.py", f"src/dep_{i}.py") for i in range(6)]
        _seed(str(tmp_path), {"src/a.py": edges_a})
        cmd_baseline(_args(str(tmp_path), "status"))  # must not raise
