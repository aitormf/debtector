"""``debtector diff --base <ref>``: the ref is indexed in a temporary worktree (pr-diff, T3)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from debtector.cli import cmd_index
from debtector.cli.pr_diff import cmd_diff
from debtector.logging import configure_logging


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout


def _worktrees(repo: Path) -> int:
    return len(_git(repo, "worktree", "list").strip().splitlines())


# The Python parser stores the import target as written, and find_cycles only follows targets
# that are indexed files, so the import names the file ("b.py") to form a real edge.
def _repo(tmp_path: Path) -> Path:
    """A git repo on ``main`` with two modules and no cycle, then a branch that adds one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("import b.py\n\n\ndef fa():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def fb():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "switch", "-q", "-c", "feature")
    (repo / "b.py").write_text("import a.py\n\n\ndef fb():\n    return 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "cycle")
    configure_logging(project=str(repo))
    cmd_index(argparse.Namespace(project=str(repo), path=str(repo), json=False))
    return repo


def _args(repo: Path, **kw) -> argparse.Namespace:
    base = {"project": str(repo), "json": True, "db_base": None, "db_pr": None, "base_ref": None}
    return argparse.Namespace(**{**base, **kw})


def test_E11_base_ref_reports_new_cycle_and_leaves_no_worktree(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:  # a new cycle is an error by default (E10)
        cmd_diff(_args(repo, base_ref="main"))

    assert exc.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["new_cycles"]
    assert _worktrees(repo) == 1


def test_E12_unknown_ref_exits_2_naming_the_ref(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="no-existe"))

    assert exc.value.code == 2
    assert "no-existe" in capsys.readouterr().err
    assert _worktrees(repo) == 1


def test_E13_base_with_index_paths_is_a_usage_error(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cmd_diff(_args(repo, base_ref="main", db_base="x.db", db_pr="y.db"))

    assert exc.value.code == 2
    assert "--base" in capsys.readouterr().err


def test_worktree_is_removed_when_indexing_fails(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("debtector.indexer.Indexer.index", boom)
    with pytest.raises(RuntimeError):
        cmd_diff(_args(repo, base_ref="main"))

    assert _worktrees(repo) == 1
