"""Tests for module-name → file-path resolution in compute_metrics.

Ca was always 0 because IMPORTS_FROM targets are stored as module names
(e.g. 'codeindex.models', '.graph_store') but File nodes are indexed by
file path (e.g. 'codeindex/models.py'). Resolution is needed for Ca to work.
"""

from __future__ import annotations

from codeindex.graph_store import GraphStore
from codeindex.metrics import compute_metrics
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


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
        """'from codeindex.models import X' → Ca of codeindex/models.py increases."""
        tmp_db.store_file(
            "codeindex/cli.py",
            [_file("codeindex/cli.py")],
            [_import("codeindex/cli.py", "codeindex.models")],
        )
        tmp_db.store_file("codeindex/models.py", [_file("codeindex/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["codeindex/models.py"].fan_in >= 1

    def test_relative_import_resolves_to_ca(self, tmp_db: GraphStore) -> None:
        """'from .models import X' → Ca of codeindex/models.py increases."""
        tmp_db.store_file(
            "codeindex/cli.py",
            [_file("codeindex/cli.py")],
            [_import("codeindex/cli.py", ".models")],
        )
        tmp_db.store_file("codeindex/models.py", [_file("codeindex/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["codeindex/models.py"].fan_in >= 1

    def test_external_package_does_not_match_internal_ca(self, tmp_db: GraphStore) -> None:
        """Import of 'networkx' (external) does not inflate Ca of any internal file."""
        tmp_db.store_file(
            "codeindex/store.py",
            [_file("codeindex/store.py")],
            [_import("codeindex/store.py", "networkx")],
        )
        tmp_db.store_file("codeindex/models.py", [_file("codeindex/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["codeindex/models.py"].fan_in == 0

    def test_subpackage_init_resolves(self, tmp_db: GraphStore) -> None:
        """'from .parser import X' resolves to codeindex/parser/__init__.py."""
        tmp_db.store_file(
            "codeindex/indexer.py",
            [_file("codeindex/indexer.py")],
            [_import("codeindex/indexer.py", ".parser")],
        )
        tmp_db.store_file(
            "codeindex/parser/__init__.py",
            [_file("codeindex/parser/__init__.py")],
            [],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["codeindex/parser/__init__.py"].fan_in >= 1

    def test_instability_correct_with_resolved_ca(self, tmp_db: GraphStore) -> None:
        """Once Ca is resolved, instability is < 1 for files that are depended upon."""
        # models.py is imported by cli.py and store.py → Ca=2, Ce=0 → I=0.0
        tmp_db.store_file(
            "codeindex/cli.py",
            [_file("codeindex/cli.py")],
            [_import("codeindex/cli.py", "codeindex.models")],
        )
        tmp_db.store_file(
            "codeindex/store.py",
            [_file("codeindex/store.py")],
            [_import("codeindex/store.py", "codeindex.models")],
        )
        tmp_db.store_file("codeindex/models.py", [_file("codeindex/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["codeindex/models.py"].fan_in == 2.0
        assert metrics["codeindex/models.py"].instability == 0.0
