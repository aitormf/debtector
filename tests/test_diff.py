"""Tests for ``debtector diff`` between two indexes (change pr-diff, T1)."""

from __future__ import annotations

import argparse
import json
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
