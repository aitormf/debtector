"""Tests for the function-complexity sections of ``debtector diff`` (pr-diff, T4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.config import load_config
from debtector.diff import compute_diff
from debtector.graph_store import GraphStore
from debtector.logging import configure_logging
from debtector.models import NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _index(path: Path, funcs: dict[str, dict[str, int]]) -> str:
    """Build an index where ``funcs[file][name]`` is the complexity of a function."""
    store = GraphStore(str(path))
    for file_path, items in funcs.items():
        nodes = [
            NodeInfo(
                kind=NodeKind.FILE,
                name=file_path.split("/")[-1],
                qualified_name=file_path,
                file_path=file_path,
                language="python",
            )
        ]
        for name, cx in items.items():
            nodes.append(
                NodeInfo(
                    kind=NodeKind.FUNCTION,
                    name=name,
                    qualified_name=f"{file_path}::{name}",
                    file_path=file_path,
                    line_start=1,
                    line_end=2,
                    language="python",
                    extra={"complexity": cx},
                )
            )
        store.store_file(file_path, nodes, [])
    store.close()
    return str(path)


def _diff(tmp_path: Path, base: dict, pr: dict) -> dict:
    b = GraphStore(_index(tmp_path / "base.db", base))
    p = GraphStore(_index(tmp_path / "pr.db", pr))
    try:
        return compute_diff(b, p, load_config(str(tmp_path)))
    finally:
        b.close()
        p.close()


def test_E14_new_function_above_threshold(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {}}, {"a.py": {"f": 21}})
    assert result["worsened_functions"] == [
        {
            "qualified_name": "a.py::f",
            "file_path": "a.py",
            "before": None,
            "after": 21,
            "severity": "medium",
        }
    ]
    assert result["improved_functions"] == []


def test_E15_function_crosses_threshold_upwards(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {"f": 18}}, {"a.py": {"f": 22}})
    [item] = result["worsened_functions"]
    assert (item["before"], item["after"]) == (18, 22)


def test_E16_already_medium_and_grows(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {"f": 25}}, {"a.py": {"f": 28}})
    [item] = result["worsened_functions"]
    assert (item["before"], item["after"], item["severity"]) == (25, 28, "medium")


def test_E17_stays_below_threshold(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {"f": 10}}, {"a.py": {"f": 20}})
    assert result["worsened_functions"] == []
    assert result["improved_functions"] == []


def test_E18_drops_below_threshold(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {"f": 32}}, {"a.py": {"f": 15}})
    assert result["worsened_functions"] == []
    [item] = result["improved_functions"]
    assert (item["qualified_name"], item["before"], item["after"]) == ("a.py::f", 32, 15)


def test_E18_removed_function_is_improvement(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"a.py": {"f": 32}}, {"a.py": {}})
    [item] = result["improved_functions"]
    assert (item["before"], item["after"]) == (32, None)


def test_E19_test_file_function_ignored(tmp_path: Path) -> None:
    result = _diff(tmp_path, {"tests/test_a.py": {}}, {"tests/test_a.py": {"test_x": 40}})
    assert result["worsened_functions"] == []
    assert result["improved_functions"] == []
