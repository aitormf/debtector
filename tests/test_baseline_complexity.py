"""``baseline save`` stores the complexity of production functions (D-0019)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from debtector.cli.baseline import cmd_baseline
from debtector.cli.common import _get_store
from debtector.logging import configure_logging
from debtector.models import NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _seed(project: str, funcs: dict[str, dict[str, int]]) -> None:
    """Index ``funcs[file][name]`` as functions with that cyclomatic complexity."""
    store = _get_store(project)
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


def _save(project: Path) -> dict:
    args = argparse.Namespace(project=str(project), json=False, baseline_cmd="save")
    cmd_baseline(args)
    return json.loads((project / ".debtector" / "baseline.json").read_text(encoding="utf-8"))


def test_E7_saves_functions_at_or_above_medium(tmp_path: Path) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 25, "h": 5}})
    snapshot = _save(tmp_path)
    assert snapshot["complexity"] == {"medium": 21, "functions": {"src/a.py::g": 25}}


def test_E8_test_functions_are_not_saved(tmp_path: Path) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 25}, "tests/test_a.py": {"test_big": 40}})
    snapshot = _save(tmp_path)
    assert snapshot["complexity"]["functions"] == {"src/a.py::g": 25}
