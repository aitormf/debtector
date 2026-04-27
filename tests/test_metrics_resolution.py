"""Tests for module-name → file-path resolution in compute_metrics.

Ca was always 0 because IMPORTS_FROM targets are stored as module names
(e.g. 'debtector.models', '.graph_store') but File nodes are indexed by
file path (e.g. 'debtector/models.py'). Resolution is needed for Ca to work.
"""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import compute_metrics
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
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


class TestModuleResolution:
    """Ca counts internal imports even when target is a module name, not a path."""

    def test_dotted_module_name_resolves_to_ca(self, tmp_db: GraphStore) -> None:
        """'from debtector.models import X' → Ca of debtector/models.py increases."""
        tmp_db.store_file(
            "debtector/cli.py",
            [_file("debtector/cli.py")],
            [_import("debtector/cli.py", "debtector.models")],
        )
        tmp_db.store_file("debtector/models.py", [_file("debtector/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["debtector/models.py"].fan_in >= 1

    def test_relative_import_resolves_to_ca(self, tmp_db: GraphStore) -> None:
        """'from .models import X' → Ca of debtector/models.py increases."""
        tmp_db.store_file(
            "debtector/cli.py",
            [_file("debtector/cli.py")],
            [_import("debtector/cli.py", ".models")],
        )
        tmp_db.store_file("debtector/models.py", [_file("debtector/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["debtector/models.py"].fan_in >= 1

    def test_external_package_does_not_match_internal_ca(self, tmp_db: GraphStore) -> None:
        """Import of 'networkx' (external) does not inflate Ca of any internal file."""
        tmp_db.store_file(
            "debtector/store.py",
            [_file("debtector/store.py")],
            [_import("debtector/store.py", "networkx")],
        )
        tmp_db.store_file("debtector/models.py", [_file("debtector/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["debtector/models.py"].fan_in == 0

    def test_subpackage_init_resolves(self, tmp_db: GraphStore) -> None:
        """'from .parser import X' resolves to debtector/parser/__init__.py."""
        tmp_db.store_file(
            "debtector/indexer.py",
            [_file("debtector/indexer.py")],
            [_import("debtector/indexer.py", ".parser")],
        )
        tmp_db.store_file(
            "debtector/parser/__init__.py",
            [_file("debtector/parser/__init__.py")],
            [],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["debtector/parser/__init__.py"].fan_in >= 1

    def test_instability_correct_with_resolved_ca(self, tmp_db: GraphStore) -> None:
        """Once Ca is resolved, instability is < 1 for files that are depended upon."""
        # models.py is imported by cli.py and store.py → Ca=2, Ce=0 → I=0.0
        tmp_db.store_file(
            "debtector/cli.py",
            [_file("debtector/cli.py")],
            [_import("debtector/cli.py", "debtector.models")],
        )
        tmp_db.store_file(
            "debtector/store.py",
            [_file("debtector/store.py")],
            [_import("debtector/store.py", "debtector.models")],
        )
        tmp_db.store_file("debtector/models.py", [_file("debtector/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["debtector/models.py"].fan_in == 2.0
        assert metrics["debtector/models.py"].instability == 0.0
