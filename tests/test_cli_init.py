"""Tests for `codeindex init` command."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codeindex.cli import _GITATTRIBUTES_LINE, _GITATTRIBUTES_MARKER, _INIT_MARKER

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository in *tmp_path* and return its root."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _run_init(git_repo: Path, extra_args: list[str] | None = None) -> None:
    """Call cmd_init via the CLI dispatcher with --project pointing to *git_repo*."""
    from codeindex.cli import cmd_init

    class _Args:
        project = str(git_repo)
        json = False

    args = _Args()
    if extra_args:
        for k, v in (a.split("=", 1) for a in extra_args):
            setattr(args, k, v)
    cmd_init(args)


# ──────────────────────────────────────────────
# .gitattributes
# ──────────────────────────────────────────────


class TestGitattributes:
    """Tests for .gitattributes patching."""

    def test_creates_gitattributes_if_missing(self, git_repo: Path) -> None:
        _run_init(git_repo)
        ga = git_repo / ".gitattributes"
        assert ga.exists()
        assert _GITATTRIBUTES_MARKER in ga.read_text()

    def test_gitattributes_contains_filter_line(self, git_repo: Path) -> None:
        _run_init(git_repo)
        content = (git_repo / ".gitattributes").read_text()
        assert _GITATTRIBUTES_LINE.strip() in content

    def test_appends_to_existing_gitattributes(self, git_repo: Path) -> None:
        ga = git_repo / ".gitattributes"
        ga.write_text("*.py text\n", encoding="utf-8")
        _run_init(git_repo)
        content = ga.read_text()
        assert "*.py text" in content
        assert _GITATTRIBUTES_MARKER in content

    def test_idempotent_gitattributes(self, git_repo: Path) -> None:
        _run_init(git_repo)
        content_first = (git_repo / ".gitattributes").read_text()
        _run_init(git_repo)
        content_second = (git_repo / ".gitattributes").read_text()
        assert content_first == content_second
        assert content_first.count(_GITATTRIBUTES_MARKER) == 1


# ──────────────────────────────────────────────
# Git hooks
# ──────────────────────────────────────────────


class TestGitHooks:
    """Tests for post-checkout / post-merge / post-rewrite hook installation."""

    @pytest.mark.parametrize("hook_name", ["post-checkout", "post-merge", "post-rewrite"])
    def test_hook_created(self, git_repo: Path, hook_name: str) -> None:
        _run_init(git_repo)
        hook = git_repo / ".git" / "hooks" / hook_name
        assert hook.exists(), f"{hook_name} not created"

    @pytest.mark.parametrize("hook_name", ["post-checkout", "post-merge", "post-rewrite"])
    def test_hook_contains_marker(self, git_repo: Path, hook_name: str) -> None:
        _run_init(git_repo)
        content = (git_repo / ".git" / "hooks" / hook_name).read_text()
        assert _INIT_MARKER in content

    @pytest.mark.parametrize("hook_name", ["post-checkout", "post-merge", "post-rewrite"])
    def test_hook_is_executable(self, git_repo: Path, hook_name: str) -> None:
        _run_init(git_repo)
        hook = git_repo / ".git" / "hooks" / hook_name
        assert os.access(hook, os.X_OK), f"{hook_name} is not executable"

    @pytest.mark.parametrize("hook_name", ["post-checkout", "post-merge", "post-rewrite"])
    def test_hook_idempotent(self, git_repo: Path, hook_name: str) -> None:
        _run_init(git_repo)
        content_first = (git_repo / ".git" / "hooks" / hook_name).read_text()
        _run_init(git_repo)
        content_second = (git_repo / ".git" / "hooks" / hook_name).read_text()
        assert content_first == content_second
        assert content_first.count(_INIT_MARKER) == 1

    @pytest.mark.parametrize("hook_name", ["post-checkout", "post-merge", "post-rewrite"])
    def test_appends_to_existing_hook(self, git_repo: Path, hook_name: str) -> None:
        hook = git_repo / ".git" / "hooks" / hook_name
        hook.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | 0o111)
        _run_init(git_repo)
        content = hook.read_text()
        assert "echo existing" in content
        assert _INIT_MARKER in content


# ──────────────────────────────────────────────
# Git config
# ──────────────────────────────────────────────


class TestGitConfig:
    """Tests for git filter/diff configuration."""

    def _git_config_get(self, repo: Path, key: str) -> str:
        result = subprocess.run(
            ["git", "config", key],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_filter_clean_configured(self, git_repo: Path) -> None:
        _run_init(git_repo)
        assert self._git_config_get(git_repo, "filter.codeindex.clean") == "codeindex-clean"

    def test_filter_smudge_configured(self, git_repo: Path) -> None:
        _run_init(git_repo)
        assert self._git_config_get(git_repo, "filter.codeindex.smudge") == "codeindex-smudge"

    def test_filter_required_false(self, git_repo: Path) -> None:
        _run_init(git_repo)
        assert self._git_config_get(git_repo, "filter.codeindex.required") == "false"

    def test_diff_textconv_configured(self, git_repo: Path) -> None:
        _run_init(git_repo)
        assert self._git_config_get(git_repo, "diff.codeindex.textconv") == "codeindex-clean"


# ──────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────


class TestInitErrors:
    """Tests for error cases."""

    def test_no_git_repo_exits_nonzero(self, tmp_path: Path) -> None:
        from codeindex.cli import cmd_init

        class _Args:
            project = str(tmp_path)
            json = False

        with pytest.raises(SystemExit) as exc:
            cmd_init(_Args())
        assert exc.value.code != 0

    def test_no_git_repo_json_output(self, tmp_path: Path) -> None:
        import json

        from codeindex.cli import cmd_init

        class _Args:
            project = str(tmp_path)
            json = True

        original_print = __builtins__["print"] if isinstance(__builtins__, dict) else print

        import builtins

        captured = []

        def fake_print(*args, **kwargs):
            captured.append(" ".join(str(a) for a in args))

        with pytest.raises(SystemExit):
            builtins.print = fake_print
            try:
                cmd_init(_Args())
            finally:
                builtins.print = original_print

        # At least one JSON-parseable line with an error key
        json_lines = [c for c in captured if c.strip().startswith("{")]
        assert any("error" in json.loads(line) for line in json_lines)
