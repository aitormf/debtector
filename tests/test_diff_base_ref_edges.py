"""Edge cases of ``debtector diff --base`` found in review (pr-diff, T3)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from test_diff_base_ref import _args, _git, _repo, _worktrees

from debtector.cli import cmd_diff, cmd_index
from debtector.indexer import Indexer


def test_project_reached_through_a_symlink(tmp_path: Path, capsys) -> None:
    """The base is the real ref: an unchanged complex function on both sides is not new."""
    repo = _repo(tmp_path)
    branches = " or ".join(f"x == {i}" for i in range(25))
    _git(repo, "switch", "-q", "main")
    (repo / "c.py").write_text(f"def fc(x):\n    return 1 if {branches} else 0\n", "utf-8")
    _git(repo, "add", "c.py")
    _git(repo, "commit", "-qm", "complex")
    _git(repo, "switch", "-q", "feature")
    _git(repo, "merge", "-q", "--no-edit", "main")
    link = tmp_path / "link"
    link.symlink_to(repo)
    cmd_index(argparse.Namespace(project=str(link), path=str(link), json=False))
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(link, base_ref="main"))

    result = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert result["new_cycles"]
    assert result["worsened_functions"] == []
    assert _worktrees(repo) == 1


def test_initialized_submodules_are_rejected(tmp_path: Path, capsys) -> None:
    """The base worktree would not contain the submodule's files: refuse instead of lying."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _git(sub, "init", "-q", "-b", "main")
    _git(sub, "config", "user.email", "t@example.com")
    _git(sub, "config", "user.name", "t")
    (sub / "s.py").write_text("def fs():\n    return 1\n", encoding="utf-8")
    _git(sub, "add", ".")
    _git(sub, "commit", "-q", "-m", "s")
    repo = _repo(tmp_path)
    _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "vendor")
    _git(repo, "commit", "-qm", "submodule")
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="main"))

    assert exc.value.code == 2
    assert "submodule" in capsys.readouterr().err
    assert _worktrees(repo) == 1


def _failing_index(fail_when):
    original = Indexer.index

    def index(self, project_path, extra_paths=None):
        stats = original(self, project_path, extra_paths=extra_paths)
        if fail_when(project_path):
            stats["errors"] += 1
        return stats

    return index


@pytest.mark.parametrize("side", ["base", "current"])
def test_indexing_errors_are_exit_2(tmp_path: Path, capsys, monkeypatch, side: str) -> None:
    """An index that could not be fully built or refreshed is not compared."""
    repo = _repo(tmp_path)
    capsys.readouterr()

    def in_worktree(path: str) -> bool:
        return "debtector-diff-" in path

    fail_when = in_worktree if side == "base" else (lambda p: not in_worktree(p))
    monkeypatch.setattr(Indexer, "index", _failing_index(fail_when))
    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="main"))

    assert exc.value.code == 2
    assert "index" in capsys.readouterr().err.lower()
    assert _worktrees(repo) == 1


def test_indexed_root_outside_the_repository_is_rejected(tmp_path: Path, capsys) -> None:
    """``index ../shared``: the base worktree cannot contain it, so an empty base would lie."""
    repo = _repo(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "s.py").write_text("def fs():\n    return 1\n", encoding="utf-8")
    cmd_index(argparse.Namespace(project=str(repo), path=str(shared), json=False))
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="main"))

    assert exc.value.code == 2
    assert "outside" in capsys.readouterr().err
    assert _worktrees(repo) == 1


def test_worktree_is_removed_when_checkout_hook_fails(tmp_path: Path, capsys) -> None:
    """A failing post-checkout hook leaves ``git worktree add`` registered despite its error."""
    repo = _repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="main"))

    assert exc.value.code == 2
    assert _worktrees(repo) == 1
