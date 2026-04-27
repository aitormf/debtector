"""Tests for the CLI --json output mode and .debtector/ directory layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from debtector.cli import (
    _debtector_dir,
    _get_store,
    cmd_imports,
    cmd_index,
    cmd_search,
    cmd_status,
    cmd_untested,
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _args(**kwargs):
    """Build a simple namespace for CLI functions."""
    import argparse

    defaults = {"project": ".", "json": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _seed_store(project: str, tmp_src: Path) -> None:
    """Index *tmp_src* into the store at *project*."""
    from debtector.indexer import Indexer

    store = _get_store(project)
    Indexer(store).index(str(tmp_src))
    store.close()


@pytest.fixture()
def project(tmp_path: Path) -> tuple[str, Path]:
    """Return (project_str, src_dir) with a minimal Python file pre-indexed."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text(
        "import os\n\nclass MyService:\n    def run(self) -> None:\n        pass\n",
        encoding="utf-8",
    )
    _seed_store(str(tmp_path), src)
    return str(tmp_path), src


# ──────────────────────────────────────────────
# .debtector/ directory layout
# ──────────────────────────────────────────────


class TestCodeindexDir:
    """The .debtector/ directory is created automatically."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """`_debtector_dir` creates the directory if absent."""
        d = _debtector_dir(str(tmp_path))
        assert d.exists()
        assert d.is_dir()
        assert d.name == ".debtector"

    def test_db_inside_debtector_dir(self, tmp_path: Path) -> None:
        """`_get_store` places index.db inside .debtector/."""
        store = _get_store(str(tmp_path))
        store.close()
        assert (tmp_path / ".debtector" / "index.db").exists()

    def test_log_file_created(self, tmp_path: Path) -> None:
        """configure_logging creates debtector.log inside .debtector/."""
        from debtector.logging import configure_logging

        configure_logging(project=str(tmp_path))
        assert (tmp_path / ".debtector" / "debtector.log").exists()

    def test_gitignore_created(self, tmp_path: Path) -> None:
        """`_debtector_dir` writes a .gitignore that ignores everything except baseline.json."""
        _debtector_dir(str(tmp_path))
        gi = tmp_path / ".debtector" / ".gitignore"
        assert gi.exists()
        content = gi.read_text(encoding="utf-8")
        assert "*\n" in content
        assert "!baseline.json\n" in content
        assert "!.gitignore\n" in content

    def test_gitignore_always_overwritten(self, tmp_path: Path) -> None:
        """Calling `_debtector_dir` always rewrites the .gitignore (managed file)."""
        _debtector_dir(str(tmp_path))
        gi = tmp_path / ".debtector" / ".gitignore"
        gi.write_text("custom\n", encoding="utf-8")
        _debtector_dir(str(tmp_path))
        content = gi.read_text(encoding="utf-8")
        assert "!baseline.json\n" in content


# ──────────────────────────────────────────────
# --json output: cmd_status
# ──────────────────────────────────────────────


class TestJsonStatus:
    """cmd_status with --json emits valid JSON with expected keys."""

    def test_status_json_keys(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        proj, _ = project
        cmd_status(_args(project=proj, json=True))
        out = json.loads(capsys.readouterr().out)
        assert "files" in out
        assert "total_nodes" in out
        assert "total_edges" in out
        assert "languages" in out
        assert "nodes_by_kind" in out
        assert "edges_by_kind" in out

    def test_status_json_counts_positive(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        proj, _ = project
        cmd_status(_args(project=proj, json=True))
        out = json.loads(capsys.readouterr().out)
        assert out["files"] > 0
        assert out["total_nodes"] > 0


# ──────────────────────────────────────────────
# --json output: cmd_search
# ──────────────────────────────────────────────


class TestJsonSearch:
    """cmd_search with --json emits a JSON array."""

    def test_search_returns_array(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        proj, _ = project
        cmd_search(_args(project=proj, json=True, query="MyService", kind=None))
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)

    def test_search_finds_class(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        proj, _ = project
        cmd_search(_args(project=proj, json=True, query="MyService", kind=None))
        out = json.loads(capsys.readouterr().out)
        names = [n["name"] for n in out]
        assert "MyService" in names

    def test_search_result_has_required_fields(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        proj, _ = project
        cmd_search(_args(project=proj, json=True, query="MyService", kind=None))
        out = json.loads(capsys.readouterr().out)
        node = next(n for n in out if n["name"] == "MyService")
        for field in ("kind", "name", "qualified_name", "file_path", "line_start"):
            assert field in node, f"missing field: {field}"

    def test_search_empty_query_returns_array(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        proj, _ = project
        cmd_search(_args(project=proj, json=True, query="nonexistent_xyz", kind=None))
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)


# ──────────────────────────────────────────────
# --json output: cmd_index
# ──────────────────────────────────────────────


class TestJsonIndex:
    """cmd_index with --json emits a stats dict."""

    def test_index_json_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=True, path=str(src)))
        out = json.loads(capsys.readouterr().out)
        assert "scanned" in out
        assert "indexed" in out
        assert "skipped" in out
        assert "errors" in out
        assert "removed" in out

    def test_index_json_counts(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=True, path=str(src)))
        out = json.loads(capsys.readouterr().out)
        assert out["scanned"] == 1
        assert out["indexed"] == 1
        assert out["errors"] == 0


# ──────────────────────────────────────────────
# --json output: cmd_imports
# ──────────────────────────────────────────────


class TestJsonImports:
    """cmd_imports with --json emits a JSON array."""

    def test_imports_returns_array(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        proj, _ = project
        cmd_imports(_args(project=proj, json=True, module="os"))
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)

    def test_imports_finds_os(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        proj, _ = project
        cmd_imports(_args(project=proj, json=True, module="os"))
        out = json.loads(capsys.readouterr().out)
        assert len(out) >= 1
        assert any("service.py" in r["file_path"] for r in out)


def _seed_untested_store(project: str, tmp_path: Path) -> None:
    """Index a minimal project with one covered (add) and one uncovered (subtract) function."""
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "math_utils.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n"
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_math.py").write_text(
        "from src.math_utils import add\n\ndef test_add():\n    add(1, 2)\n"
    )
    from debtector.indexer import Indexer

    store = _get_store(project)
    Indexer(store).index(str(tmp_path))
    store.close()


class TestJsonUntested:
    """cmd_untested with --json emits a JSON array of uncovered symbols."""

    @pytest.fixture()
    def untested_project(self, tmp_path: Path) -> str:
        """Return project path with one covered (add) and one uncovered (subtract) function."""
        _seed_untested_store(str(tmp_path), tmp_path)
        return str(tmp_path)

    def test_returns_array(self, untested_project: str, capsys: pytest.CaptureFixture) -> None:
        cmd_untested(_args(project=untested_project, json=True, path=None))
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)

    def test_uncovered_symbol_present(
        self, untested_project: str, capsys: pytest.CaptureFixture
    ) -> None:
        cmd_untested(_args(project=untested_project, json=True, path=None))
        out = json.loads(capsys.readouterr().out)
        names = {n["name"] for n in out}
        assert "subtract" in names

    def test_covered_symbol_absent(
        self, untested_project: str, capsys: pytest.CaptureFixture
    ) -> None:
        cmd_untested(_args(project=untested_project, json=True, path=None))
        out = json.loads(capsys.readouterr().out)
        names = {n["name"] for n in out}
        assert "add" not in names

    def test_result_has_required_fields(
        self, untested_project: str, capsys: pytest.CaptureFixture
    ) -> None:
        cmd_untested(_args(project=untested_project, json=True, path=None))
        out = json.loads(capsys.readouterr().out)
        assert len(out) > 0
        node = out[0]
        for field in ("kind", "name", "qualified_name", "file_path"):
            assert field in node, f"missing field: {field}"

    def test_path_filter(self, untested_project: str, capsys: pytest.CaptureFixture) -> None:
        cmd_untested(_args(project=untested_project, json=True, path="src/math_utils.py"))
        out = json.loads(capsys.readouterr().out)
        assert all(n["file_path"] == "src/math_utils.py" for n in out)

    def test_no_test_functions_in_output(
        self, untested_project: str, capsys: pytest.CaptureFixture
    ) -> None:
        cmd_untested(_args(project=untested_project, json=True, path=None))
        out = json.loads(capsys.readouterr().out)
        for node in out:
            assert not node["file_path"].startswith("tests/")
