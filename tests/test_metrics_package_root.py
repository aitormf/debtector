"""T2: absolute Python imports resolve from the package root (R2, D-0016)."""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import METRICS_VERSION, compute_metrics
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


def _by_path(store: GraphStore) -> dict[str, tuple[float, float]]:
    return {m.file_path: (m.fan_in, m.fan_out) for m in compute_metrics(store)}


def test_E5_src_layout_absolute_import(tmp_db: GraphStore) -> None:
    # D-0016
    _add(tmp_db, "src/blib2to3/__init__.py")
    _add(tmp_db, "src/blib2to3/pgen2/__init__.py")
    _add(tmp_db, "src/blib2to3/pgen2/grammar.py")
    _add(tmp_db, "src/blib2to3/pytree.py", "blib2to3.pgen2.grammar")
    m = _by_path(tmp_db)
    assert m["src/blib2to3/pytree.py"][1] == 1
    assert m["src/blib2to3/pgen2/grammar.py"][0] == 1


def test_E6_import_of_module_by_package_name(tmp_db: GraphStore) -> None:
    # D-0016
    _add(tmp_db, "src/blib2to3/__init__.py")
    _add(tmp_db, "src/blib2to3/pytree.py")
    _add(tmp_db, "src/blib2to3/x.py", "blib2to3.pytree")
    assert _by_path(tmp_db)["src/blib2to3/x.py"][1] == 1


def test_E7_flat_layout_still_resolves(tmp_db: GraphStore) -> None:
    _add(tmp_db, "app/__init__.py")
    _add(tmp_db, "app/models.py")
    _add(tmp_db, "app/views.py", "app.models")
    assert _by_path(tmp_db)["app/views.py"][1] == 1


def test_E8_ambiguous_name_is_not_resolved(tmp_db: GraphStore) -> None:
    # D-0016
    _add(tmp_db, "scripts/utils.py")
    _add(tmp_db, "tools/utils.py")
    _add(tmp_db, "a.py", "utils")
    m = _by_path(tmp_db)
    assert m["a.py"][1] == 0
    assert m["scripts/utils.py"][0] == 0
    assert m["tools/utils.py"][0] == 0


def test_E9_metrics_version_bumped() -> None:
    assert METRICS_VERSION >= 8
