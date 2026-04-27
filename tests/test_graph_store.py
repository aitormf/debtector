"""Tests for debtector.graph_store.GraphStore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from debtector.graph_store import CURRENT_SCHEMA_VERSION, GraphStore, SchemaTooNewError
from debtector.models import EdgeKind, NodeInfo, NodeKind


class TestStoreFile:
    """Tests for GraphStore.store_file()."""

    def test_stores_nodes(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "hash1")
        nodes = tmp_db.get_nodes_by_file("src/app.py")
        assert len(nodes) == 3

    def test_stores_edges(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "hash1")
        edges = tmp_db.get_outgoing("src/app.py")
        # CONTAINS + IMPORTS_FROM go out from the file node
        assert len(edges) == 2

    def test_reindex_replaces_previous_data(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "hash1")
        # Re-index with fewer nodes
        minimal = [simple_nodes[0]]  # only the File node
        tmp_db.store_file("src/app.py", minimal, [], "hash2")
        nodes = tmp_db.get_nodes_by_file("src/app.py")
        assert len(nodes) == 1

    def test_file_hash_stored(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "deadbeef")
        assert tmp_db.get_file_hash("src/app.py") == "deadbeef"

    def test_empty_nodes_and_edges(self, tmp_db: GraphStore) -> None:
        tmp_db.store_file("empty.py", [], [], "hash0")
        assert tmp_db.get_nodes_by_file("empty.py") == []


class TestRemoveFile:
    """Tests for GraphStore.remove_file()."""

    def test_removes_nodes_and_edges(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        tmp_db.remove_file("src/app.py")
        assert tmp_db.get_nodes_by_file("src/app.py") == []
        assert tmp_db.get_outgoing("src/app.py") == []

    def test_remove_nonexistent_is_noop(self, tmp_db: GraphStore) -> None:
        tmp_db.remove_file("does_not_exist.py")  # should not raise


class TestGetNode:
    """Tests for GraphStore.get_node()."""

    def test_returns_node_by_qualified_name(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        node = tmp_db.get_node("src/app.py::MyService")
        assert node is not None
        assert node.name == "MyService"
        assert node.kind == NodeKind.CLASS

    def test_returns_none_for_unknown(self, tmp_db: GraphStore) -> None:
        result = tmp_db.get_node("nonexistent::Symbol")
        assert result is None


class TestGetAllFiles:
    """Tests for GraphStore.get_all_files()."""

    def test_returns_indexed_files(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        files = tmp_db.get_all_files()
        assert "src/app.py" in files

    def test_returns_empty_when_no_files(self, tmp_db: GraphStore) -> None:
        assert tmp_db.get_all_files() == []

    def test_returns_multiple_files(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        other = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="utils.py",
                qualified_name="src/utils.py",
                file_path="src/utils.py",
            )
        ]
        tmp_db.store_file("src/utils.py", other, [], "h2")
        files = tmp_db.get_all_files()
        assert len(files) == 2


class TestSearchNodes:
    """Tests for GraphStore.search_nodes()."""

    def test_finds_by_name(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db.search_nodes("MyService")
        names = [n.name for n in results]
        assert "MyService" in names

    def test_filters_by_kind(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db.search_nodes("MyService", kind=NodeKind.CLASS)
        assert all(n.kind == NodeKind.CLASS for n in results)

    def test_and_logic_across_words(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        # "my service" should match "MyService" (both words appear in the name)
        results = tmp_db.search_nodes("my service")
        assert any(n.name == "MyService" for n in results)

    def test_empty_query_returns_empty(self, tmp_db: GraphStore) -> None:
        results = tmp_db.search_nodes("")
        assert results == []

    def test_no_match_returns_empty(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db.search_nodes("nonexistentsymbol")
        assert results == []


class TestSearchImports:
    """Tests for GraphStore.search_imports()."""

    def test_finds_import(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db.search_imports("flask")
        assert len(results) == 1
        assert results[0]["file_path"] == "src/app.py"

    def test_no_match_returns_empty(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        assert tmp_db.search_imports("django") == []


class TestEdgeQueries:
    """Tests for get_outgoing / get_incoming."""

    def test_get_outgoing(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        edges = tmp_db.get_outgoing("src/app.py")
        assert len(edges) == 2  # CONTAINS + IMPORTS_FROM

    def test_get_outgoing_filtered_by_kind(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        edges = tmp_db.get_outgoing("src/app.py", edge_kind=EdgeKind.IMPORTS_FROM)
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.IMPORTS_FROM

    def test_get_incoming(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        edges = tmp_db.get_incoming("src/app.py::MyService")
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.CONTAINS

    def test_get_incoming_filtered_by_kind(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        edges = tmp_db.get_incoming("src/app.py::MyService", edge_kind=EdgeKind.HAS_METHOD)
        assert edges == []  # HAS_METHOD goes class→method, not into MyService from above


class TestGetImpactRadius:
    """Tests for GraphStore.get_impact_radius()."""

    def test_changed_file_appears_in_result(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        result = tmp_db.get_impact_radius(["src/app.py"])
        changed_qns = {n.qualified_name for n in result["changed_nodes"]}
        assert "src/app.py" in changed_qns

    def test_result_keys_present(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        result = tmp_db.get_impact_radius(["src/app.py"])
        assert "changed_nodes" in result
        assert "impacted_nodes" in result
        assert "impacted_files" in result
        assert "edges" in result
        assert "depth_reached" in result

    def test_nonexistent_file_returns_empty(self, tmp_db: GraphStore) -> None:
        result = tmp_db.get_impact_radius(["does_not_exist.py"])
        assert result["changed_nodes"] == []
        assert result["impacted_nodes"] == []


class TestGetStats:
    """Tests for GraphStore.get_stats()."""

    def test_stats_after_store(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        stats = tmp_db.get_stats()
        assert stats.total_nodes == 3
        assert stats.total_edges == 3
        assert stats.files_count == 1
        assert "python" in stats.languages
        assert stats.nodes_by_kind[NodeKind.CLASS] == 1
        assert stats.nodes_by_kind[NodeKind.METHOD] == 1

    def test_stats_empty_store(self, tmp_db: GraphStore) -> None:
        stats = tmp_db.get_stats()
        assert stats.total_nodes == 0
        assert stats.total_edges == 0
        assert stats.files_count == 0


class TestMetadata:
    """Tests for set_metadata / get_metadata."""

    def test_set_and_get(self, tmp_db: GraphStore) -> None:
        tmp_db.set_metadata("schema_version", "1")
        assert tmp_db.get_metadata("schema_version") == "1"

    def test_overwrite_existing(self, tmp_db: GraphStore) -> None:
        tmp_db.set_metadata("key", "old")
        tmp_db.set_metadata("key", "new")
        assert tmp_db.get_metadata("key") == "new"

    def test_missing_key_returns_none(self, tmp_db: GraphStore) -> None:
        assert tmp_db.get_metadata("nonexistent") is None


class TestContextManager:
    """Tests for GraphStore as context manager."""

    def test_context_manager(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        with GraphStore(db_path) as store:
            store.set_metadata("k", "v")
            assert store.get_metadata("k") == "v"
        # After exit, connection should be closed (no assertion needed — no exception = ok)


class TestSchemaMigrations:
    """Tests for automatic schema migration on DB open."""

    def test_fresh_db_gets_current_version(self, tmp_path: Path) -> None:
        """A brand-new database must have schema_version set to CURRENT_SCHEMA_VERSION."""
        db_path = tmp_path / "fresh.db"
        with GraphStore(db_path) as store:
            version = store.get_metadata("schema_version")
        assert version == str(CURRENT_SCHEMA_VERSION)

    def test_reopening_does_not_change_version(self, tmp_path: Path) -> None:
        """Opening an up-to-date DB a second time must leave schema_version unchanged."""
        db_path = tmp_path / "stable.db"
        with GraphStore(db_path) as store:
            v1 = store.get_metadata("schema_version")
        with GraphStore(db_path) as store:
            v2 = store.get_metadata("schema_version")
        assert v1 == v2 == str(CURRENT_SCHEMA_VERSION)

    def test_legacy_db_without_version_gets_migrated(self, tmp_path: Path) -> None:
        """A DB with no schema_version entry (legacy) must be migrated on open."""
        db_path = tmp_path / "legacy.db"
        # Simulate an old DB: create the metadata table but omit the schema_version row.
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
        conn.close()

        with GraphStore(db_path) as store:
            version = store.get_metadata("schema_version")
        assert version == str(CURRENT_SCHEMA_VERSION)

    def test_too_new_schema_raises_error(self, tmp_path: Path) -> None:
        """A DB whose schema_version exceeds CURRENT_SCHEMA_VERSION must raise SchemaTooNewError."""
        db_path = tmp_path / "future.db"
        # Create a valid DB, then manually bump the version beyond what the code knows.
        with GraphStore(db_path) as store:
            store.set_metadata("schema_version", str(CURRENT_SCHEMA_VERSION + 1))

        with pytest.raises(SchemaTooNewError):
            GraphStore(db_path)
