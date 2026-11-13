"""T1: test files do not count in the coupling metrics (D-0015)."""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import METRICS_VERSION, compute_metrics, find_cycles, god_modules
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _add(store: GraphStore, path: str, *targets: str) -> None:
    node = NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )
    edges = [
        EdgeInfo(kind=EdgeKind.IMPORTS_FROM, source=path, target=t, file_path=path, line=1)
        for t in targets
    ]
    store.store_file(path, [node], edges)


def test_E1_tests_do_not_add_ca(tmp_db: GraphStore) -> None:
    _add(tmp_db, "src/app/models.py")
    for i in range(3):
        _add(tmp_db, f"src/app/prod_{i}.py", "src/app/models.py")
    for i in range(20):
        _add(tmp_db, f"tests/test_{i}.py", "src/app/models.py")
    by_path = {m.file_path: m for m in compute_metrics(tmp_db)}
    assert by_path["src/app/models.py"].fan_in == 3
    assert not any(p.startswith("tests/") for p in by_path)


def test_E1_test_files_do_not_form_cycles(tmp_db: GraphStore) -> None:
    _add(tmp_db, "src/a.py", "tests/test_a.py")
    _add(tmp_db, "tests/test_a.py", "src/a.py")
    assert find_cycles(tmp_db) == []


def test_E2_test_helper_is_not_a_god_module(tmp_db: GraphStore) -> None:
    _add(tmp_db, "tests/utils.py")
    for i in range(15):
        _add(tmp_db, f"tests/test_{i}.py", "tests/utils.py")
    for i in range(5):
        _add(tmp_db, f"src/m{i}.py")
    assert god_modules(tmp_db) == []
    assert "tests/utils.py" not in {m.file_path for m in compute_metrics(tmp_db)}


def test_E3_percentile_is_over_production_modules(tmp_db: GraphStore) -> None:
    for i in range(5):
        _add(tmp_db, f"src/m{i}.py")
    _add(tmp_db, "src/hub.py")
    for i in range(50):
        _add(tmp_db, f"tests/test_{i}.py")
    # Over 6 production modules the hub (Ca=2) is an outlier; over 56 it would sit at the 0 floor
    _add(tmp_db, "src/u1.py", "src/hub.py")
    _add(tmp_db, "src/u2.py", "src/hub.py")
    assert [m.file_path for m in god_modules(tmp_db)] == ["src/hub.py"]
    assert len(compute_metrics(tmp_db)) == 8


def test_E4_metrics_version_bumped() -> None:
    assert METRICS_VERSION == 5
