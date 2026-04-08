"""Tests for Indexer error paths and edge cases."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from codeindex.graph_store import GraphStore
from codeindex.indexer import Indexer
from codeindex.parser.base import LanguageParser


@pytest.fixture()
def project_dir(tmp_path: Path, sample_fixture_path: Path) -> Path:
    """Create a temporary project directory with sample.py.

    Args:
        tmp_path: Pytest temporary directory.
        sample_fixture_path: Path to the sample Python fixture file.

    Returns:
        Path to the project root (parent of the src/ subdirectory).
    """
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(sample_fixture_path, src / "sample.py")
    return tmp_path


@pytest.fixture()
def store_and_indexer(tmp_path: Path, project_dir: Path):
    """Return (GraphStore, Indexer) pair pointed at the temp project.

    Args:
        tmp_path: Pytest temporary directory.
        project_dir: Project root fixture.

    Yields:
        Tuple of (GraphStore, Indexer).
    """
    db_path = tmp_path / ".codeindex.db"
    store = GraphStore(db_path)
    indexer = Indexer(store)
    yield store, indexer
    store.close()


# ──────────────────────────────────────────────
# Parser not found (line 109)
# ──────────────────────────────────────────────


class TestIndexerNoParser:
    """Tests for the 'parser is None' branch (line 109)."""

    def test_skips_file_when_no_parser(self, store_and_indexer, project_dir: Path) -> None:
        """Files with no matching parser are scanned but not indexed."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "get_parser", return_value=None):
            stats = indexer.index(str(project_dir))
        assert stats["scanned"] >= 1
        assert stats["indexed"] == 0

    def test_error_count_unchanged_when_no_parser(
        self, store_and_indexer, project_dir: Path
    ) -> None:
        """Skipping a file due to no parser does not increment errors."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "get_parser", return_value=None):
            stats = indexer.index(str(project_dir))
        assert stats["errors"] == 0


# ──────────────────────────────────────────────
# file_hash error (lines 113-116)
# ──────────────────────────────────────────────


class TestIndexerFileHashError:
    """Tests for the file_hash exception path (lines 113-116)."""

    def test_hash_error_increments_errors(self, store_and_indexer, project_dir: Path) -> None:
        """An OSError from file_hash increments the error counter."""
        store, indexer = store_and_indexer
        with patch.object(LanguageParser, "file_hash", side_effect=OSError("permission denied")):
            stats = indexer.index(str(project_dir))
        assert stats["errors"] >= 1

    def test_hash_error_does_not_index_file(self, store_and_indexer, project_dir: Path) -> None:
        """A file whose hash cannot be computed is not indexed."""
        store, indexer = store_and_indexer
        with patch.object(LanguageParser, "file_hash", side_effect=OSError("permission denied")):
            stats = indexer.index(str(project_dir))
        assert stats["indexed"] == 0


# ──────────────────────────────────────────────
# parse returns None (lines 152-153)
# ──────────────────────────────────────────────


class TestIndexerParseNone:
    """Tests for the 'parse returned None' path (lines 152-153)."""

    def test_parse_none_increments_errors(self, store_and_indexer, project_dir: Path) -> None:
        """When parse() returns None the error counter is incremented."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "parse", return_value=None):
            stats = indexer.index(str(project_dir))
        assert stats["errors"] >= 1

    def test_parse_none_nothing_indexed(self, store_and_indexer, project_dir: Path) -> None:
        """When parse() returns None no nodes are stored."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "parse", return_value=None):
            stats = indexer.index(str(project_dir))
        assert stats["indexed"] == 0
        assert store.get_all_files() == []


# ──────────────────────────────────────────────
# parse raises exception (lines 154-156)
# ──────────────────────────────────────────────


class TestIndexerParseException:
    """Tests for the parse exception catch-all (lines 154-156)."""

    def test_parse_exception_increments_errors(self, store_and_indexer, project_dir: Path) -> None:
        """A RuntimeError from parse() is caught and counted as an error."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "parse", side_effect=RuntimeError("parser crashed")):
            stats = indexer.index(str(project_dir))
        assert stats["errors"] >= 1

    def test_parse_exception_does_not_propagate(self, store_and_indexer, project_dir: Path) -> None:
        """Exceptions from parse() are swallowed and indexing continues."""
        store, indexer = store_and_indexer
        with patch.object(indexer.registry, "parse", side_effect=RuntimeError("parser crashed")):
            stats = indexer.index(str(project_dir))
        # Should complete without raising, returning a stats dict
        assert isinstance(stats, dict)
        assert "errors" in stats


# ──────────────────────────────────────────────
# ignore_files (line 185-186)
# ──────────────────────────────────────────────


class TestIndexerIgnoreFiles:
    """Tests for the ignore_files filtering in _discover_files (line 186)."""

    def test_ignores_custom_filename(self, tmp_path: Path) -> None:
        """A file whose name is in ignore_files is not yielded by _discover_files."""
        src = tmp_path / "src"
        src.mkdir()
        # A Python file that should be indexed normally
        (src / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        # A Python file whose exact name is in ignore_files — should be skipped
        (src / "excluded.py").write_text("EXCLUDED = True\n", encoding="utf-8")

        db_path = tmp_path / ".codeindex.db"
        store = GraphStore(db_path)
        indexer = Indexer(store, ignore_files={"excluded.py"})
        stats = indexer.index(str(src))

        files = store.get_all_files()
        store.close()

        assert not any("excluded.py" in f for f in files)
        assert stats["scanned"] >= 1

    def test_ignores_ds_store_by_default(self, tmp_path: Path) -> None:
        """.DS_Store is in the default ignore list and never surfaced."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")
        # .DS_Store has no supported extension so it won't be picked up anyway,
        # but we validate the ignore_files set contains it
        db_path = tmp_path / ".codeindex.db"
        store = GraphStore(db_path)
        indexer = Indexer(store)
        assert ".DS_Store" in indexer.ignore_files
        store.close()

    def test_custom_ignore_does_not_affect_other_files(self, tmp_path: Path) -> None:
        """Files NOT in ignore_files are still indexed normally."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "keep.py").write_text("def keep(): pass\n", encoding="utf-8")
        (src / "skip.py").write_text("def skip(): pass\n", encoding="utf-8")

        db_path = tmp_path / ".codeindex.db"
        store = GraphStore(db_path)
        indexer = Indexer(store, ignore_files={"skip.py"})
        indexer.index(str(src))

        files = store.get_all_files()
        store.close()

        assert any("keep.py" in f for f in files)
        assert not any("skip.py" in f for f in files)
