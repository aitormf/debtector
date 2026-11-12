"""Tests for ``debtector diff`` between two indexes (change pr-diff, T1)."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest
from debtector.diff import compute_diff, instability_regressions

from debtector.cli import cmd_diff
from debtector.config import load_config
from debtector.graph_store import GraphStore
from debtector.logging import configure_logging
from debtector.metrics import ModuleMetrics
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


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
        kind=EdgeKind.IMPORTS_FROM, source=source, target=target, file_path=source, line=1
    )


def _index(path: Path, files: dict[str, list[str]]) -> str:
    """Build an index at *path* where ``files[src]`` lists the files src imports."""
    store = GraphStore(str(path))
    for src, targets in files.items():
        store.store_file(src, [_file(src)], [_import(src, t) for t in targets])
    store.close()
    return str(path)


def _diff(base: str, pr: str, project: Path) -> dict:
    b, p = GraphStore(base), GraphStore(pr)
    try:
        return compute_diff(b, p, load_config(str(project)))
    finally:
        b.close()
        p.close()


def _mm(path: str, instability: float) -> ModuleMetrics:
    return ModuleMetrics(file_path=path, fan_in=1.0, fan_out=1.0, instability=instability)


def test_E1_cycle_only_in_pr_is_new(tmp_path: Path) -> None:
    base = _index(tmp_path / "base.db", {"a.py": [], "b.py": []})
    pr = _index(tmp_path / "pr.db", {"a.py": ["b.py"], "b.py": ["a.py"]})
    result = _diff(base, pr, tmp_path)
    assert [sorted(c) for c in result["new_cycles"]] == [["a.py", "b.py"]]
    assert result["resolved_cycles"] == []


def test_E2_cycle_gone_in_pr_is_resolved(tmp_path: Path) -> None:
    base = _index(tmp_path / "base.db", {"a.py": ["b.py"], "b.py": ["a.py"]})
    pr = _index(tmp_path / "pr.db", {"a.py": [], "b.py": []})
    result = _diff(base, pr, tmp_path)
    assert [sorted(c) for c in result["resolved_cycles"]] == [["a.py", "b.py"]]
    assert result["new_cycles"] == []


def test_E3_same_cycle_in_other_order_is_not_new(tmp_path: Path) -> None:
    base = _index(tmp_path / "base.db", {"a.py": ["b.py"], "b.py": ["a.py"]})
    pr = _index(tmp_path / "pr.db", {"b.py": ["a.py"], "a.py": ["b.py"]})
    result = _diff(base, pr, tmp_path)
    assert result["new_cycles"] == []
    assert result["resolved_cycles"] == []


def test_E4_module_only_in_pr_is_not_an_instability_regression() -> None:
    assert instability_regressions([_mm("a.py", 0.1)], [_mm("a.py", 0.1), _mm("new.py", 1.0)]) == []


def test_E5_instability_tolerance_is_inclusive() -> None:
    base = [_mm("a.py", 0.40)]
    assert instability_regressions(base, [_mm("a.py", 0.45)]) == []
    result = instability_regressions(base, [_mm("a.py", 0.46)])
    assert [(r["file_path"], r["before"], r["after"]) for r in result] == [("a.py", 0.4, 0.46)]


def test_E6_god_modules_new_and_resolved(tmp_path: Path) -> None:
    (tmp_path / "debtector.toml").write_text(
        "[metrics.thresholds]\ngod_module_min_ca = 2\n", encoding="utf-8"
    )
    plain = _index(
        tmp_path / "plain.db", {"hub.py": [], "m0.py": [], "m1.py": [], "m2.py": [], "m3.py": []}
    )
    hub = _index(
        tmp_path / "hub.db",
        {"hub.py": [], "m0.py": ["hub.py"], "m1.py": ["hub.py"], "m2.py": ["hub.py"], "m3.py": []},
    )

    appeared = _diff(plain, hub, tmp_path)
    assert appeared["new_god_modules"] == ["hub.py"]
    assert appeared["resolved_god_modules"] == []

    gone = _diff(hub, plain, tmp_path)
    assert gone["resolved_god_modules"] == ["hub.py"]
    assert gone["new_god_modules"] == []


def test_E7_equal_indexes_give_empty_diff_and_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"a.py": ["b.py"], "b.py": []}
    base = _index(tmp_path / "base.db", files)
    pr = _index(tmp_path / "pr.db", files)
    result = _diff(base, pr, tmp_path)
    assert all(v == [] for v in result.values())

    cmd_diff(
        argparse.Namespace(project=str(tmp_path), json=False, db_base=base, db_pr=pr, base=None)
    )
    assert "No architectural changes" in capsys.readouterr().out

    cmd_diff(
        argparse.Namespace(project=str(tmp_path), json=True, db_base=base, db_pr=pr, base=None)
    )
    assert json.loads(capsys.readouterr().out) == result


def test_instability_delta_exactly_at_tolerance_despite_float_rounding() -> None:
    """0.35 + 0.05 is 0.39999999999999997 in floating point: 0.35 → 0.40 is not a regression."""
    base = [_mm("a.py", 7 / 20)]  # Ca=13, Ce=7
    assert instability_regressions(base, [_mm("a.py", 8 / 20)]) == []  # Ca=12, Ce=8


def test_instability_delta_just_above_tolerance_is_a_regression() -> None:
    """Ca=23, Ce=20 → Ca=16, Ce=17 grows instability by ~0.05004: above the tolerance."""
    base = [_mm("a.py", 20 / 43)]
    assert len(instability_regressions(base, [_mm("a.py", 17 / 33)])) == 1


# ── T2: input validation and exit code ──


def _run_diff(project: Path, base: str, pr: str) -> int:
    """Run ``cmd_diff`` and return its exit code (0 if it returns normally)."""
    args = argparse.Namespace(project=str(project), json=False, db_base=base, db_pr=pr, base=None)
    try:
        cmd_diff(args)
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _set_parser_version(db: str, version: str) -> None:
    store = GraphStore(db)
    store.set_metadata("parser_version", version)
    store.close()


def test_E8_different_parser_version_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:  # D-0008
    base = _index(tmp_path / "base.db", {"a.py": []})
    pr = _index(tmp_path / "pr.db", {"a.py": []})
    _set_parser_version(base, "1")
    _set_parser_version(pr, "2")
    assert _run_diff(tmp_path, base, pr) == 2
    err = capsys.readouterr().err
    assert "parser_version" in err
    assert "debtector index" in err


def test_E9_missing_path_is_exit_2_and_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pr = _index(tmp_path / "pr.db", {"a.py": []})
    missing = str(tmp_path / "nope.db")
    assert _run_diff(tmp_path, missing, pr) == 2
    assert missing in capsys.readouterr().err
    assert not Path(missing).exists()


def test_E9_file_that_is_not_an_index_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pr = _index(tmp_path / "pr.db", {"a.py": []})
    junk = tmp_path / "junk.db"
    junk.write_text("not a database", encoding="utf-8")
    assert _run_diff(tmp_path, pr, str(junk)) == 2
    assert str(junk) in capsys.readouterr().err

    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE t (x)")
    conn.close()
    assert _run_diff(tmp_path, str(other), pr) == 2


def test_E10_new_cycle_severity_error_is_exit_1_warning_is_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:  # D-0008
    base = _index(tmp_path / "base.db", {"a.py": [], "b.py": []})
    pr = _index(tmp_path / "pr.db", {"a.py": ["b.py"], "b.py": ["a.py"]})

    (tmp_path / "debtector.toml").write_text('[metrics.severity]\ncycles = "error"\n', "utf-8")
    assert _run_diff(tmp_path, base, pr) == 1
    assert "New cycles" in capsys.readouterr().out

    (tmp_path / "debtector.toml").write_text('[metrics.severity]\ncycles = "warning"\n', "utf-8")
    assert _run_diff(tmp_path, base, pr) == 0
    assert "New cycles" in capsys.readouterr().out


def test_resolved_cycle_alone_does_not_fail(tmp_path: Path) -> None:
    base = _index(tmp_path / "base.db", {"a.py": ["b.py"], "b.py": ["a.py"]})
    pr = _index(tmp_path / "pr.db", {"a.py": [], "b.py": []})
    assert _run_diff(tmp_path, base, pr) == 0


def test_tables_with_incompatible_columns_are_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tables named like an index but with other columns: exit 2, not a traceback."""
    pr = _index(tmp_path / "pr.db", {"a.py": []})
    fake = tmp_path / "fake.db"
    conn = sqlite3.connect(fake)
    conn.executescript(
        "CREATE TABLE nodes (x); CREATE TABLE edges (x); CREATE TABLE metadata (key, value);"
    )
    conn.close()
    assert _run_diff(tmp_path, str(fake), pr) == 2
    assert str(fake) in capsys.readouterr().err
