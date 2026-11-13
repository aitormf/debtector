"""JS/TS test-file conventions: ``test/``, ``__tests__/`` and tsx/jsx/mjs/cjs suffixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.graph_store import GraphStore
from debtector.metrics import METRICS_VERSION, compute_metrics, god_modules
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind
from debtector.parser import PARSER_VERSION


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("test/helpers/with-server.ts", True),
        ("test/app.router.js", True),
        ("packages/core/test/a.ts", True),
        ("__tests__/a.ts", True),
        ("src/components/__tests__/button.tsx", True),
        ("src/button.test.tsx", True),
        ("src/button.spec.jsx", True),
        ("src/a.test.mjs", True),
        ("src/a.spec.cjs", True),
        ("src/a.test.jsx", True),
        ("src/a.spec.tsx", True),
        ("latest/x.ts", False),
        ("src/contest/x.ts", False),
        ("src/testing.ts", False),
        ("src/attest/x.js", False),
        ("src/test.ts", False),
    ],
)
def test_is_test_path_js_conventions(tmp_path: Path, path: str, expected: bool) -> None:
    store = GraphStore(tmp_path / "x.db")
    try:
        assert store.is_test_path(path) is expected
    finally:
        store.close()


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


def test_singular_test_dir_out_of_metrics(tmp_db: GraphStore) -> None:
    """got-like layout: helpers under ``test/`` are neither modules nor dependents."""
    _add(tmp_db, "source/core/options.ts")
    _add(tmp_db, "source/index.ts", "source/core/options.ts")
    _add(tmp_db, "test/helpers/with-server.ts", "source/index.ts")
    for i in range(15):
        _add(tmp_db, f"test/case_{i}.ts", "test/helpers/with-server.ts", "source/index.ts")
    by_path = {m.file_path: m for m in compute_metrics(tmp_db)}
    assert set(by_path) == {"source/core/options.ts", "source/index.ts"}
    assert by_path["source/index.ts"].fan_in == 0
    assert not any(g.file_path.startswith("test/") for g in god_modules(tmp_db))


def test_versions_bumped() -> None:
    """Metrics change, and existing indexes must re-parse to reclassify test files."""
    assert METRICS_VERSION >= 11
    assert PARSER_VERSION >= 8
