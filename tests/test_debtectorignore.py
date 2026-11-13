"""Tests for .debtectorignore support in Indexer."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from debtector.graph_store import GraphStore
from debtector.indexer import IgnoreRules, Indexer

# ──────────────────────────────────────────────
# IgnoreRules unit tests
# ──────────────────────────────────────────────


class TestIgnoreRulesFromFile:
    """Tests for IgnoreRules.from_file() factory."""

    def test_returns_empty_rules_when_file_absent(self, tmp_path: Path) -> None:
        """No .debtectorignore → no patterns, nothing is ignored."""
        rules = IgnoreRules.from_file(tmp_path)
        assert not rules.is_ignored("src/app.py")

    def test_parses_simple_pattern(self, tmp_path: Path) -> None:
        """A plain filename pattern is loaded and matched."""
        (tmp_path / ".debtectorignore").write_text("generated.py\n", encoding="utf-8")
        rules = IgnoreRules.from_file(tmp_path)
        assert rules.is_ignored("generated.py")

    def test_ignores_blank_lines(self, tmp_path: Path) -> None:
        """Blank lines in .debtectorignore do not create patterns."""
        (tmp_path / ".debtectorignore").write_text("\n\ngenerated.py\n\n", encoding="utf-8")
        rules = IgnoreRules.from_file(tmp_path)
        assert rules.is_ignored("generated.py")
        assert not rules.is_ignored("app.py")

    def test_ignores_comment_lines(self, tmp_path: Path) -> None:
        """Lines starting with # are comments and are not matched."""
        (tmp_path / ".debtectorignore").write_text(
            "# this is a comment\ngenerated.py\n", encoding="utf-8"
        )
        rules = IgnoreRules.from_file(tmp_path)
        assert rules.is_ignored("generated.py")
        assert not rules.is_ignored("# this is a comment")

    def test_strips_inline_whitespace(self, tmp_path: Path) -> None:
        """Leading/trailing whitespace around patterns is stripped."""
        (tmp_path / ".debtectorignore").write_text("  generated.py  \n", encoding="utf-8")
        rules = IgnoreRules.from_file(tmp_path)
        assert rules.is_ignored("generated.py")


class TestIgnoreRulesMatching:
    """Tests for IgnoreRules.is_ignored() pattern matching."""

    def test_exact_filename_match(self) -> None:
        """An exact filename pattern matches that filename anywhere in the tree."""
        rules = IgnoreRules(["secret.py"])
        assert rules.is_ignored("secret.py")
        assert rules.is_ignored("src/secret.py")
        assert rules.is_ignored("a/b/c/secret.py")

    def test_exact_filename_no_match(self) -> None:
        """A filename pattern does not match a different filename."""
        rules = IgnoreRules(["secret.py"])
        assert not rules.is_ignored("not_secret.py")
        assert not rules.is_ignored("src/app.py")

    def test_wildcard_extension_pattern(self) -> None:
        """*.generated.py matches any file ending in .generated.py."""
        rules = IgnoreRules(["*.generated.py"])
        assert rules.is_ignored("models.generated.py")
        assert rules.is_ignored("src/models.generated.py")
        assert not rules.is_ignored("models.py")

    def test_directory_pattern_with_trailing_slash(self) -> None:
        """A pattern ending in / prunes the entire directory subtree."""
        rules = IgnoreRules(["tests/"])
        assert rules.is_ignored("tests/test_app.py")
        assert rules.is_ignored("tests/unit/test_models.py")
        assert not rules.is_ignored("src/app.py")

    def test_directory_pattern_without_trailing_slash(self) -> None:
        """A bare directory name (no slash) also matches files inside it."""
        rules = IgnoreRules(["vendor"])
        assert rules.is_ignored("vendor/lib.py")
        assert rules.is_ignored("vendor/sub/lib.py")
        assert not rules.is_ignored("src/lib.py")

    def test_glob_star_in_path(self) -> None:
        """Glob * in a path segment matches any single segment."""
        rules = IgnoreRules(["src/*/generated.py"])
        assert rules.is_ignored("src/auth/generated.py")
        assert rules.is_ignored("src/api/generated.py")
        assert not rules.is_ignored("src/generated.py")
        assert not rules.is_ignored("src/auth/other.py")

    def test_multiple_patterns(self) -> None:
        """Any one pattern matching is sufficient to ignore a path."""
        rules = IgnoreRules(["tests/", "*.log"])
        assert rules.is_ignored("tests/test_app.py")
        assert rules.is_ignored("debug.log")
        assert not rules.is_ignored("src/app.py")

    def test_no_patterns_never_ignores(self) -> None:
        """Empty rules never ignore anything."""
        rules = IgnoreRules([])
        assert not rules.is_ignored("anything/at/all.py")


# ──────────────────────────────────────────────
# Indexer integration tests
# ──────────────────────────────────────────────


@pytest.fixture()
def project_dir(tmp_path: Path, sample_fixture_path: Path) -> Path:
    """Temporary project with src/sample.py."""
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(sample_fixture_path, src / "sample.py")
    return tmp_path


@pytest.fixture()
def store(tmp_path: Path, project_dir: Path) -> GraphStore:
    """GraphStore pointing at a temp DB."""
    db_path = tmp_path / ".debtector.db"
    s = GraphStore(db_path)
    yield s
    s.close()


class TestIndexerReadsIgnoreFile:
    """Integration: Indexer skips files/dirs matching .debtectorignore."""

    def test_ignores_file_matching_pattern(self, store: GraphStore, project_dir: Path) -> None:
        """A file whose name matches a .debtectorignore pattern is not indexed."""
        (project_dir / "src" / "secret.py").write_text("PASSWORD = 'hunter2'\n", encoding="utf-8")
        (project_dir / ".debtectorignore").write_text("secret.py\n", encoding="utf-8")

        indexer = Indexer(store)
        indexer.index(str(project_dir))

        files = store.get_all_files()
        assert not any("secret.py" in f for f in files)

    def test_non_ignored_files_still_indexed(self, store: GraphStore, project_dir: Path) -> None:
        """Files not matching any pattern are still indexed normally."""
        (project_dir / ".debtectorignore").write_text("secret.py\n", encoding="utf-8")

        indexer = Indexer(store)
        indexer.index(str(project_dir))

        files = store.get_all_files()
        assert any("sample.py" in f for f in files)

    def test_ignores_directory_via_pattern(self, store: GraphStore, project_dir: Path) -> None:
        """A directory pattern prunes the whole subtree from indexing."""
        generated = project_dir / "generated"
        generated.mkdir()
        (generated / "schema.py").write_text("class Schema: pass\n", encoding="utf-8")
        (project_dir / ".debtectorignore").write_text("generated/\n", encoding="utf-8")

        indexer = Indexer(store)
        indexer.index(str(project_dir))

        files = store.get_all_files()
        assert not any("generated" in f for f in files)

    def test_no_ignore_file_indexes_everything(self, store: GraphStore, project_dir: Path) -> None:
        """Without a .debtectorignore, all supported files are indexed."""
        extra = project_dir / "extra.py"
        extra.write_text("x = 1\n", encoding="utf-8")

        indexer = Indexer(store)
        indexer.index(str(project_dir))

        files = store.get_all_files()
        assert any("sample.py" in f for f in files)
        assert any("extra.py" in f for f in files)

    def test_wildcard_pattern_ignores_matching_files(
        self, store: GraphStore, project_dir: Path
    ) -> None:
        """A glob pattern like *.generated.py excludes matching files."""
        (project_dir / "src" / "models.generated.py").write_text(
            "class M: pass\n", encoding="utf-8"
        )
        (project_dir / ".debtectorignore").write_text("*.generated.py\n", encoding="utf-8")

        indexer = Indexer(store)
        indexer.index(str(project_dir))

        files = store.get_all_files()
        assert not any("models.generated.py" in f for f in files)
        assert any("sample.py" in f for f in files)
