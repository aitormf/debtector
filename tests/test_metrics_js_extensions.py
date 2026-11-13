"""T3: a .js/.jsx import also resolves to the .ts/.tsx file of the same name (R3)."""

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
        language="typescript",
    )
    edges = [
        EdgeInfo(kind=EdgeKind.IMPORTS_FROM, source=path, target=t, file_path=path, line=1)
        for t in targets
    ]
    store.store_file(path, [node], edges)


def _by_path(store: GraphStore) -> dict[str, tuple[float, float]]:
    return {m.file_path: (m.fan_in, m.fan_out) for m in compute_metrics(store)}


def test_E10_js_import_resolves_to_ts(tmp_db: GraphStore) -> None:
    _add(tmp_db, "source/index.ts", "./core/options.js")
    _add(tmp_db, "source/core/options.ts")
    m = _by_path(tmp_db)
    assert m["source/index.ts"][1] == 1
    assert m["source/core/options.ts"][0] == 1


def test_E11_exact_file_wins_over_ts(tmp_db: GraphStore) -> None:
    _add(tmp_db, "m.ts", "./a/x.js")
    _add(tmp_db, "a/x.js")
    _add(tmp_db, "a/x.ts")
    m = _by_path(tmp_db)
    assert m["a/x.js"][0] == 1
    assert m["a/x.ts"][0] == 0


def test_E12_jsx_import_resolves_to_tsx(tmp_db: GraphStore) -> None:
    _add(tmp_db, "app.tsx", "./c.jsx")
    _add(tmp_db, "c.tsx")
    m = _by_path(tmp_db)
    assert m["app.tsx"][1] == 1
    assert m["c.tsx"][0] == 1


def test_E13_metrics_version_bumped() -> None:
    assert METRICS_VERSION >= 5
