"""A production file is "untested" only when none of its functions/methods has COVERS.

Gherkin contract:
    Given un fichero con 10 métodos, 9 cubiertos
    When se calculan los ficheros sin tests
    Then no aparece (E1)

    Given un fichero con 3 funciones, ninguna cubierta
    When se calculan los ficheros sin tests
    Then aparece y es candidato a untested_high_coupling (E2)

    Given un fichero sin funciones ni métodos (solo constantes)
    When se calculan los ficheros sin tests
    Then no aparece (E3)
"""

from __future__ import annotations

from pathlib import Path

from debtector.audit.testrisk import untested_high_coupling
from debtector.cli import _get_uncovered_files
from debtector.graph_store import GraphStore
from debtector.metrics import ModuleMetrics
from debtector.models import EdgeInfo, NodeInfo


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind="File", name=path, qualified_name=path, file_path=path,
        line_start=1, line_end=100, language="python",
    )  # fmt: skip


def _func(path: str, name: str, kind: str = "Function") -> NodeInfo:
    return NodeInfo(
        kind=kind, name=name, qualified_name=f"{path}::{name}", file_path=path,
        line_start=2, line_end=3, language="python",
    )  # fmt: skip


def _covers(test_path: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind="COVERS", source=f"{test_path}::test_x", target=target, file_path=test_path, line=1
    )


def _store(tmp_path: Path, files: dict[str, list[NodeInfo]], covered: list[str]) -> GraphStore:
    store = GraphStore(tmp_path / "index.db")
    for path, symbols in files.items():
        store.store_file(path, [_file(path), *symbols], [])
    test_path = "tests/test_x.py"
    store.store_file(
        test_path,
        [_file(test_path), _func(test_path, "test_x")],
        [_covers(test_path, t) for t in covered],
    )
    return store


def test_E1_partially_covered_file_is_not_untested(tmp_path: Path) -> None:
    path = "src/svc.py"
    methods = [_func(path, f"C.m{i}", "Method") for i in range(10)]
    store = _store(tmp_path, {path: methods}, [m.qualified_name for m in methods[:9]])
    try:
        assert path not in _get_uncovered_files(store)
    finally:
        store.close()


def test_E2_file_with_no_covered_function_is_untested(tmp_path: Path) -> None:
    path = "src/risky.py"
    funcs = [_func(path, f"f{i}") for i in range(3)]
    store = _store(tmp_path, {path: funcs}, [])
    try:
        uncovered = _get_uncovered_files(store)
    finally:
        store.close()
    assert path in uncovered
    metrics = [ModuleMetrics(file_path=path, fan_in=0.0, fan_out=15.0, instability=1.0)]
    findings = untested_high_coupling(uncovered, metrics, ce_threshold=10)
    assert [f.file_path for f in findings] == [path]


def test_E3_file_without_functions_is_not_untested(tmp_path: Path) -> None:
    path = "src/constants.py"
    store = _store(tmp_path, {path: []}, [])
    try:
        assert path not in _get_uncovered_files(store)
    finally:
        store.close()
