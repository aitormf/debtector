"""T6: an index.js/.ts/.jsx/.tsx without classes or functions is a pure facade (R6, D-0017)."""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import METRICS_VERSION, sdp_violations
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _add(store: GraphStore, path: str, *targets: str, function: str | None = None) -> None:
    nodes = [
        NodeInfo(
            kind=NodeKind.FILE,
            name=path.split("/")[-1],
            qualified_name=path,
            file_path=path,
            language="typescript",
        )
    ]
    if function:
        nodes.append(
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name=function,
                qualified_name=f"{path}::{function}",
                file_path=path,
                language="typescript",
            )
        )
    edges = [
        EdgeInfo(kind=EdgeKind.IMPORTS_FROM, source=path, target=t, file_path=path, line=1)
        for t in targets
    ]
    store.store_file(path, nodes, edges)


def _build(store: GraphStore, function: str | None) -> None:
    # lib/index.ts: Ca 2, Ce 1 (I 0.33); lib/a.ts: Ca 1, Ce 4 (I 0.8) -> index -> a violates SDP.
    _add(store, "lib/index.ts", "./a.js", function=function)
    _add(store, "lib/a.ts", "./l1.js", "./l2.js", "./l3.js", "./l4.js")
    for n in range(1, 5):
        _add(store, f"lib/l{n}.ts")
    _add(store, "app/x.ts", "../lib/index.js")
    _add(store, "app/y.ts", "../lib/index.js")


def test_E22_index_without_definitions_is_a_pure_facade(tmp_db: GraphStore) -> None:
    _build(tmp_db, None)
    assert sdp_violations(tmp_db) == []


def test_E23_index_with_a_function_stays_in_sdp(tmp_db: GraphStore) -> None:
    _build(tmp_db, "create")
    pairs = [(v.source, v.target) for v in sdp_violations(tmp_db)]
    assert ("lib/index.ts", "lib/a.ts") in pairs


def test_E24_metrics_version_bumped() -> None:
    assert METRICS_VERSION >= 9
