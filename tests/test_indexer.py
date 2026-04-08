"""Integration tests for codeindex.indexer.Indexer."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from codeindex.graph_store import GraphStore
from codeindex.indexer import Indexer


@pytest.fixture()
def project_dir(tmp_path: Path, sample_fixture_path: Path) -> Path:
    """Create a temporary project directory with sample.py."""
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(sample_fixture_path, src / "sample.py")
    return tmp_path


@pytest.fixture()
def store_and_indexer(tmp_path: Path, project_dir: Path):
    """Return (GraphStore, Indexer) pair pointed at the temp project."""
    db_path = tmp_path / ".codeindex.db"
    store = GraphStore(db_path)
    indexer = Indexer(store)
    yield store, indexer
    store.close()


class TestIndexerFirstRun:
    """Tests for the initial indexing pass."""

    def test_scans_and_indexes_files(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        stats = indexer.index(str(project_dir))
        assert stats["scanned"] >= 1
        assert stats["indexed"] >= 1
        assert stats["errors"] == 0

    def test_nodes_stored_after_index(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))
        files = store.get_all_files()
        assert len(files) >= 1

    def test_symbols_searchable_after_index(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))
        results = store.search_nodes("UserService")
        assert any(n.name == "UserService" for n in results)

    def test_stats_reflect_indexed_content(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))
        graph_stats = store.get_stats()
        assert graph_stats.total_nodes > 0
        assert graph_stats.total_edges > 0


class TestIndexerIncrementalUpdate:
    """Tests for incremental re-indexing."""

    def test_reindex_without_changes_skips_all(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))
        stats2 = indexer.index(str(project_dir))
        assert stats2["skipped"] >= 1
        assert stats2["indexed"] == 0

    def test_reindex_after_file_change_re_indexes(
        self, store_and_indexer, project_dir: Path
    ) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))

        # Modify the file
        sample = project_dir / "src" / "sample.py"
        content = sample.read_text()
        sample.write_text(content + "\n# modified\n")

        stats2 = indexer.index(str(project_dir))
        assert stats2["indexed"] >= 1
        assert stats2["skipped"] == 0

    def test_reindex_after_file_deletion_removes_it(
        self, store_and_indexer, project_dir: Path
    ) -> None:
        store, indexer = store_and_indexer
        indexer.index(str(project_dir))

        # Delete the file
        sample = project_dir / "src" / "sample.py"
        sample.unlink()

        stats2 = indexer.index(str(project_dir))
        assert stats2["removed"] >= 1

        files = store.get_all_files()
        assert len(files) == 0


class TestIndexerIgnoreRules:
    """Tests for directory and file ignore rules."""

    def test_ignores_pycache(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        pycache = project_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "dummy.py").write_text("x = 1")

        indexer.index(str(project_dir))
        files = store.get_all_files()
        assert not any("__pycache__" in f for f in files)

    def test_ignores_venv(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        venv = project_dir / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("x = 1")

        indexer.index(str(project_dir))
        files = store.get_all_files()
        assert not any(".venv" in f for f in files)

    def test_only_indexes_supported_extensions(self, store_and_indexer, project_dir: Path) -> None:
        store, indexer = store_and_indexer
        (project_dir / "README.md").write_text("# readme")
        (project_dir / "config.yaml").write_text("key: value")

        indexer.index(str(project_dir))
        files = store.get_all_files()
        assert not any(f.endswith(".md") for f in files)
        assert not any(f.endswith(".yaml") for f in files)
