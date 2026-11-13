"""Tests for the god-module minimum Ca and Stable Dependencies Principle violations."""

from __future__ import annotations

import pytest

from debtector.graph_store import GraphStore
from debtector.metrics import compute_metrics, god_modules, sdp_violations
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


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


def _add(store: GraphStore, path: str, *targets: str) -> None:
    store.store_file(path, [_file(path)], [_import(path, t) for t in targets])


def _hub(store: GraphStore, ca: int) -> None:
    """One module ``src/hub.py`` imported by ``ca`` modules, plus a few quiet ones."""
    _add(store, "src/hub.py")
    for i in range(ca):
        _add(store, f"src/user_{i}.py", "src/hub.py")
    for i in range(10):
        _add(store, f"src/quiet_{i}.py")


class TestGodModuleMinCa:
    def test_high_percentile_but_below_min_ca_is_not_god(self, tmp_db: GraphStore) -> None:
        _hub(tmp_db, 5)
        assert [m.file_path for m in god_modules(tmp_db)] == ["src/hub.py"]
        assert god_modules(tmp_db, min_ca=10) == []

    def test_above_percentile_and_min_ca_is_god(self, tmp_db: GraphStore) -> None:
        _hub(tmp_db, 12)
        gods = god_modules(tmp_db, min_ca=10)
        assert [m.file_path for m in gods] == ["src/hub.py"]

    def test_min_ca_is_inclusive(self, tmp_db: GraphStore) -> None:
        _hub(tmp_db, 10)
        assert len(god_modules(tmp_db, min_ca=10)) == 1
        assert god_modules(tmp_db, min_ca=11) == []


class TestSdpViolations:
    def _stable_depends_on_unstable(self, store: GraphStore) -> None:
        # a: Ca=3, Ce=1 -> I=0.25 ; b: Ca=1, Ce=2 -> I=0.667 ; a -> b violates SDP
        for i in range(3):
            _add(store, f"src/x{i}.py", "src/a.py")
        _add(store, "src/a.py", "src/b.py")
        _add(store, "src/b.py", "src/f.py", "src/r.py")
        _add(store, "src/f.py")
        _add(store, "src/r.py")

    def test_stable_to_unstable_edge_is_flagged(self, tmp_db: GraphStore) -> None:
        self._stable_depends_on_unstable(tmp_db)
        found = sdp_violations(tmp_db)
        assert [(v.source, v.target) for v in found] == [("src/a.py", "src/b.py")]
        v = found[0]
        assert v.source_instability == pytest.approx(0.25)
        assert v.target_instability == pytest.approx(2 / 3)

    def test_unstable_to_stable_edge_is_not_flagged(self, tmp_db: GraphStore) -> None:
        self._stable_depends_on_unstable(tmp_db)
        # x_i (I=1) -> a (I=0.25) is fine
        assert ("src/x0.py", "src/a.py") not in {
            (v.source, v.target) for v in sdp_violations(tmp_db)
        }

    def test_leaf_with_instability_one_is_not_flagged(self, tmp_db: GraphStore) -> None:
        self._stable_depends_on_unstable(tmp_db)
        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/x0.py"].instability == 1.0
        assert "src/x0.py" not in {v.target for v in sdp_violations(tmp_db)}

    def test_margin_is_respected(self, tmp_db: GraphStore) -> None:
        self._stable_depends_on_unstable(tmp_db)
        assert len(sdp_violations(tmp_db, margin=0.4)) == 1
        assert sdp_violations(tmp_db, margin=0.5) == []

    def test_no_violation_on_empty_index(self, tmp_db: GraphStore) -> None:
        assert sdp_violations(tmp_db) == []

    def test_external_imports_are_ignored(self, tmp_db: GraphStore) -> None:
        _add(tmp_db, "src/a.py", "flask")
        assert sdp_violations(tmp_db) == []


def _class(path: str, name: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.CLASS,
        name=name,
        qualified_name=f"{path}::{name}",
        file_path=path,
        language="python",
    )


def _stable_to_unstable(
    store: GraphStore, src: str, tgt: str, src_extra: list[NodeInfo] | None = None
) -> None:
    """``src`` (Ca=3, Ce=1, I=0.25) imports ``tgt`` (Ca=1, Ce=2, I=0.667)."""
    for i in range(3):
        _add(store, f"src/x{i}.py", src)
    store.store_file(src, [_file(src), *(src_extra or [])], [_import(src, tgt)])
    _add(store, tgt, "src/f.py", "src/r.py")
    _add(store, "src/f.py")
    _add(store, "src/r.py")


class TestPureFacadesOutOfSdp:
    """A __init__.py without classes or functions is not part of SDP (R4, D-0013)."""

    def test_E13_facade_as_source(self, tmp_db: GraphStore) -> None:
        _stable_to_unstable(tmp_db, "src/audit/__init__.py", "src/audit/x.py")
        assert sdp_violations(tmp_db) == []

    def test_E14_facade_as_target(self, tmp_db: GraphStore) -> None:
        # c (I=0.25) -> pkg/__init__ (I=0.667), facade as destination
        _stable_to_unstable(tmp_db, "src/c.py", "src/pkg/__init__.py")
        assert sdp_violations(tmp_db) == []

    def test_E15_init_with_a_class_still_counts(self, tmp_db: GraphStore) -> None:
        path = "src/parser/__init__.py"
        _stable_to_unstable(tmp_db, "src/indexer.py", path)
        # same shape, but the __init__ defines a class: it is not a facade
        tmp_db.store_file(
            path,
            [_file(path), _class(path, "ParserRegistry")],
            [_import(path, "src/f.py"), _import(path, "src/r.py")],
        )
        found = sdp_violations(tmp_db, margin=0.1)
        assert [(v.source, v.target) for v in found] == [("src/indexer.py", path)]

    def test_E16_metrics_version_is_4(self) -> None:
        from debtector.metrics import METRICS_VERSION

        assert METRICS_VERSION == 4
