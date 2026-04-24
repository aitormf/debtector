"""Tests for god module detection in metrics.py."""

from __future__ import annotations

from codeindex.graph_store import GraphStore
from codeindex.metrics import compute_metrics, god_modules
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


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
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


def _store_with_fan_ins(tmp_db: GraphStore, fan_ins: list[int]) -> None:
    """Store N files where file i has fan_in[i] importers."""
    paths = [f"src/mod_{i}.py" for i in range(len(fan_ins))]
    for path in paths:
        tmp_db.store_file(path, [_file(path)], [])

    importer_idx = len(fan_ins)
    for target_idx, ca in enumerate(fan_ins):
        for _ in range(ca):
            importer = f"src/importer_{importer_idx}.py"
            tmp_db.store_file(
                importer,
                [_file(importer)],
                [_import(importer, paths[target_idx])],
            )
            importer_idx += 1


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


class TestGodModules:
    """Unit tests for god_modules()."""

    def test_empty_store_returns_empty(self, tmp_db: GraphStore) -> None:
        """An empty index has no god modules."""
        assert god_modules(tmp_db) == []

    def test_no_importers_no_god_module(self, tmp_db: GraphStore) -> None:
        """Isolated files are never god modules."""
        for p in ["src/a.py", "src/b.py", "src/c.py"]:
            tmp_db.store_file(p, [_file(p)], [])

        assert god_modules(tmp_db) == []

    def test_single_file_never_god_module(self, tmp_db: GraphStore) -> None:
        """A single file cannot be a statistical outlier."""
        tmp_db.store_file("src/a.py", [_file("src/a.py")], [])
        assert god_modules(tmp_db) == []

    def test_outlier_detected_above_p90(self, tmp_db: GraphStore) -> None:
        """A module with Ca far above the p90 of the project is flagged."""
        # 9 modules with Ca=1, 1 module with Ca=20 → clear outlier
        _store_with_fan_ins(tmp_db, [1, 1, 1, 1, 1, 1, 1, 1, 1, 20])

        gods = god_modules(tmp_db)
        assert len(gods) >= 1
        # The outlier should be the last module (Ca=20)
        god_paths = {m.file_path for m in gods}
        assert "src/mod_9.py" in god_paths

    def test_uniform_distribution_no_god_module(self, tmp_db: GraphStore) -> None:
        """When all modules have the same Ca, none is an outlier."""
        _store_with_fan_ins(tmp_db, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3])

        assert god_modules(tmp_db) == []

    def test_returns_module_metrics_instances(self, tmp_db: GraphStore) -> None:
        """god_modules returns ModuleMetrics objects (subset of compute_metrics)."""
        from codeindex.metrics import ModuleMetrics

        _store_with_fan_ins(tmp_db, [1, 1, 1, 1, 1, 1, 1, 1, 1, 20])

        gods = god_modules(tmp_db)
        for g in gods:
            assert isinstance(g, ModuleMetrics)

    def test_god_modules_subset_of_compute_metrics(self, tmp_db: GraphStore) -> None:
        """Every god module appears in compute_metrics output."""
        _store_with_fan_ins(tmp_db, [1, 1, 1, 1, 1, 1, 1, 1, 1, 20])

        all_metrics = {m.file_path for m in compute_metrics(tmp_db)}
        gods = god_modules(tmp_db)
        for g in gods:
            assert g.file_path in all_metrics

    def test_custom_percentile(self, tmp_db: GraphStore) -> None:
        """A lower percentile threshold flags more modules."""
        _store_with_fan_ins(tmp_db, [1, 2, 3, 4, 5, 6, 7, 8, 9, 20])

        gods_p90 = god_modules(tmp_db, percentile=90)
        gods_p50 = god_modules(tmp_db, percentile=50)
        assert len(gods_p50) >= len(gods_p90)

    def test_invalid_percentile_raises(self, tmp_db: GraphStore) -> None:
        """percentile outside [1, 99] raises ValueError (not IndexError)."""
        import pytest

        with pytest.raises(ValueError, match="percentile"):
            god_modules(tmp_db, percentile=100)

        with pytest.raises(ValueError, match="percentile"):
            god_modules(tmp_db, percentile=0)
