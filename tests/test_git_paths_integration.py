"""Integration tests against a real git repository.

The unit tests in ``test_git_history.py`` mock ``git``; these ones run it, to
catch mismatches between the paths stored in the graph (relative to the
indexed directory) and the paths ``git`` reports (relative to the repo root).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — tests drive a local throwaway git repo
from pathlib import Path

import pytest

from debtector.cli import _get_store, cmd_bus_factor, cmd_hotspots, cmd_index
from debtector.git_history import compute_temporal_coupling
from debtector.logging import configure_logging

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repo whose code lives under ``src/``: ``a.py`` imports ``b``."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "dev@example.com")
    _git(root, "config", "user.name", "Dev")
    _git(root, "config", "commit.gpgsign", "false")
    for i in range(3):
        _commit(
            root,
            {
                "src/pkg/a.py": f"from pkg.b import f\n\nX = {i}\n",
                "src/pkg/b.py": f"def f():\n    return {i}\n",
            },
            f"change {i}",
        )
    return root


def _args(project: str, **kwargs) -> argparse.Namespace:
    defaults = {
        "project": project,
        "json": True,
        "limit": None,
        "since": None,
        "min_shared": 1,
        "min_ratio": 0.0,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _json(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class TestSubdirectoryIndex:
    """``debtector index ./src`` stores paths relative to ``src/``."""

    def test_hotspots_match_git_history(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_index(_args(str(repo), path=str(repo / "src"), json=True))
        capsys.readouterr()

        cmd_hotspots(_args(str(repo)))

        hotspots = {h["file_path"]: h for h in _json(capsys)["hotspots"]}
        assert set(hotspots) == {"pkg/a.py", "pkg/b.py"}
        assert hotspots["pkg/a.py"]["churn"] == 3

    def test_bus_factor_blames_indexed_files(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_index(_args(str(repo), path=str(repo / "src"), json=True))
        capsys.readouterr()

        cmd_bus_factor(_args(str(repo)))

        files = {b["file_path"] for b in _json(capsys)["bus_factor"]}
        assert files == {"pkg/a.py", "pkg/b.py"}

    def test_auto_index_keeps_indexed_root(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_index(_args(str(repo), path=str(repo / "src"), json=True))
        (repo / "src/pkg/c.py").write_text("from pkg.a import X\n", encoding="utf-8")
        capsys.readouterr()

        cmd_hotspots(_args(str(repo)))
        capsys.readouterr()

        store = _get_store(str(repo))
        files = set(store.get_all_files())
        store.close()
        assert files == {"pkg/a.py", "pkg/b.py", "pkg/c.py"}


class TestAutoIndex:
    def test_analysis_command_indexes_without_explicit_index(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_hotspots(_args(str(repo)))

        files = {h["file_path"] for h in _json(capsys)["hotspots"]}
        assert files == {"src/pkg/a.py", "src/pkg/b.py"}


class TestTemporalCouplingCurrentFiles:
    def test_deleted_and_renamed_files_are_dropped(self, repo: Path) -> None:
        _git(repo, "mv", "src/pkg/b.py", "src/pkg/renamed.py")
        _git(repo, "commit", "-q", "-m", "rename b")
        _commit(repo, {"src/pkg/a.py": "X = 9\n", "src/pkg/renamed.py": "Y = 1\n"}, "edit")

        pairs = compute_temporal_coupling(repo, min_shared=1, min_ratio=0.0)

        files = {p.file_a for p in pairs} | {p.file_b for p in pairs}
        assert "src/pkg/b.py" not in files
        assert files == {"src/pkg/a.py", "src/pkg/renamed.py"}
