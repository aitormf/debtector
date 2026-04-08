"""Tests for the CLI --json output mode and .codeindex/ directory layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from codeindex.cli import (
    _HOOK_MARKER,
    _codeindex_dir,
    _find_git_hooks,
    _get_store,
    cmd_imports,
    cmd_index,
    cmd_install_hook,
    cmd_install_skill,
    cmd_search,
    cmd_status,
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
    from codeindex.indexer import Indexer

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
# .codeindex/ directory layout
# ──────────────────────────────────────────────


class TestCodeindexDir:
    """The .codeindex/ directory is created automatically."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """`_codeindex_dir` creates the directory if absent."""
        d = _codeindex_dir(str(tmp_path))
        assert d.exists()
        assert d.is_dir()
        assert d.name == ".codeindex"

    def test_db_inside_codeindex_dir(self, tmp_path: Path) -> None:
        """`_get_store` places index.db inside .codeindex/."""
        store = _get_store(str(tmp_path))
        store.close()
        assert (tmp_path / ".codeindex" / "index.db").exists()

    def test_log_file_created(self, tmp_path: Path) -> None:
        """configure_logging creates codeindex.log inside .codeindex/."""
        from codeindex.logging import configure_logging

        configure_logging(project=str(tmp_path))
        assert (tmp_path / ".codeindex" / "codeindex.log").exists()

    def test_gitignore_created(self, tmp_path: Path) -> None:
        """`_codeindex_dir` writes a .gitignore that ignores everything except *.db."""
        _codeindex_dir(str(tmp_path))
        gi = tmp_path / ".codeindex" / ".gitignore"
        assert gi.exists()
        content = gi.read_text(encoding="utf-8")
        assert "*\n" in content
        assert "!*.db\n" in content
        assert "!.gitignore\n" in content

    def test_gitignore_not_overwritten(self, tmp_path: Path) -> None:
        """Calling `_codeindex_dir` twice does not overwrite an existing .gitignore."""
        _codeindex_dir(str(tmp_path))
        gi = tmp_path / ".codeindex" / ".gitignore"
        gi.write_text("custom\n", encoding="utf-8")
        _codeindex_dir(str(tmp_path))
        assert gi.read_text(encoding="utf-8") == "custom\n"


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


# ──────────────────────────────────────────────
# install-skill
# ──────────────────────────────────────────────


class TestInstallSkill:
    """cmd_install_skill copies skill files to the target directory."""

    def test_installs_to_project(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        dest = tmp_path / ".claude" / "skills"
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        assert dest.exists()
        md_files = list(dest.glob("*.md"))
        assert len(md_files) >= 2

    def test_installs_codeindex_skill(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        dest = tmp_path / ".claude" / "skills"
        assert (dest / "codeindex.md").exists()

    def test_installs_bootstrap_skill(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        dest = tmp_path / ".claude" / "skills"
        assert (dest / "codeindex-bootstrap.md").exists()

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        cmd_install_skill(_args(project=str(tmp_path), json=True, global_install=False))
        out = json.loads(capsys.readouterr().out)
        assert "installed" in out
        assert "dest" in out
        assert len(out["installed"]) >= 2


# ──────────────────────────────────────────────
# install-hook
# ──────────────────────────────────────────────


def _fake_git_repo(base: Path) -> Path:
    """Create a minimal .git/hooks/ structure and return the hooks dir."""
    hooks = base / ".git" / "hooks"
    hooks.mkdir(parents=True)
    return hooks


class TestFindGitHooks:
    """_find_git_hooks walks up to find .git/hooks/."""

    def test_finds_in_current_dir(self, tmp_path: Path) -> None:
        _fake_git_repo(tmp_path)
        result = _find_git_hooks(str(tmp_path))
        assert result is not None
        assert result.name == "hooks"

    def test_finds_in_parent(self, tmp_path: Path) -> None:
        _fake_git_repo(tmp_path)
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        result = _find_git_hooks(str(subdir))
        assert result is not None

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        result = _find_git_hooks(str(tmp_path))
        assert result is None


class TestInstallHook:
    """cmd_install_hook installs a pre-commit hook."""

    def test_creates_hook_file(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.exists()

    def test_hook_contains_marker(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert _HOOK_MARKER in hook.read_text(encoding="utf-8")

    def test_hook_is_executable(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.stat().st_mode & 0o111

    def test_hook_has_shebang(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.read_text(encoding="utf-8").startswith("#!/bin/sh")

    def test_idempotent(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        content_first = (tmp_path / ".git" / "hooks" / "pre-commit").read_text()
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        content_second = (tmp_path / ".git" / "hooks" / "pre-commit").read_text()
        assert content_first == content_second
        # Marker appears exactly once
        assert content_first.count(_HOOK_MARKER) == 1

    def test_appends_to_existing_hook(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        hooks = _fake_git_repo(tmp_path)
        existing = hooks / "pre-commit"
        existing.write_text("#!/bin/sh\necho 'existing hook'\n", encoding="utf-8")
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        content = existing.read_text(encoding="utf-8")
        assert "existing hook" in content
        assert _HOOK_MARKER in content

    def test_add_to_stage_includes_git_add(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=True))
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert "git add .codeindex/index.db" in hook.read_text(encoding="utf-8")

    def test_json_output_created(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=True, add_to_stage=False))
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "created"
        assert "path" in out

    def test_json_output_already_installed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=True, add_to_stage=False))
        capsys.readouterr()
        cmd_install_hook(_args(project=str(tmp_path), json=True, add_to_stage=False))
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "already_installed"

    def test_error_when_no_git(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            cmd_install_hook(_args(project=str(tmp_path), json=True, add_to_stage=False))
        assert exc.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
