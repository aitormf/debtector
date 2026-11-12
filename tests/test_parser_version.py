"""A change in parser output (``PARSER_VERSION``) forces a full re-parse on ``index``."""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.graph_store import GraphStore
from debtector.indexer import Indexer
from debtector.parser import PARSER_VERSION


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def f(x):\n    if x:\n        return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def store(tmp_path: Path):
    s = GraphStore(tmp_path / "idx.db")
    yield s
    s.close()


def test_parser_version_is_recorded_after_index(project: Path, store: GraphStore) -> None:
    Indexer(store).index(str(project))

    assert store.get_metadata("parser_version") == str(PARSER_VERSION)


def test_unchanged_files_are_skipped_when_version_matches(project: Path, store: GraphStore) -> None:
    Indexer(store).index(str(project))

    stats = Indexer(store).index(str(project))

    assert stats["indexed"] == 0
    assert stats["skipped"] == 2


def test_version_mismatch_reparses_unchanged_files(project: Path, store: GraphStore) -> None:
    Indexer(store).index(str(project))
    store.set_metadata("parser_version", "0")

    stats = Indexer(store).index(str(project))

    assert stats["indexed"] == 2
    assert stats["skipped"] == 0
    assert store.get_metadata("parser_version") == str(PARSER_VERSION)
    # and the next run is incremental again
    assert Indexer(store).index(str(project))["skipped"] == 2


def test_index_without_version_key_reparses_and_backfills_complexity(
    project: Path, store: GraphStore
) -> None:
    """An index built before complexity existed has no key and no values."""
    Indexer(store).index(str(project))
    store._conn.execute("DELETE FROM metadata WHERE key = 'parser_version'")
    store._conn.execute("UPDATE nodes SET extra = '{}'")
    store._conn.commit()

    Indexer(store).index(str(project))

    node = store.get_node("a.py::f")
    assert node is not None
    assert node.extra["complexity"] == 2


def test_parser_version_is_5() -> None:
    assert PARSER_VERSION == 5


def test_failed_reparse_does_not_advance_parser_version(project: Path, store: GraphStore) -> None:
    Indexer(store).index(str(project))
    store.set_metadata("parser_version", "0")
    indexer = Indexer(store)
    real_parse = indexer.registry.parse

    def flaky(file_path: str, is_test: bool | None = None):
        if file_path.endswith("b.py"):
            raise RuntimeError("boom")
        return real_parse(file_path, is_test)

    indexer.registry.parse = flaky  # type: ignore[method-assign]

    stats = indexer.index(str(project))

    assert stats["errors"] == 1
    assert store.get_metadata("parser_version") == "0"

    # next run (parser healthy again) reparses everything and completes the migration
    stats = Indexer(store).index(str(project))
    assert stats["indexed"] == 2
    assert stats["errors"] == 0
    assert store.get_metadata("parser_version") == str(PARSER_VERSION)
