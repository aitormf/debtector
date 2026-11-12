"""Hotspot sections of ``debtector diff`` (pr-diff, T5): E20, E21, E22."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from test_diff_complexity import _index

from debtector.cli import cmd_diff
from debtector.logging import configure_logging

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([*_GIT, *args], cwd=cwd, check=True, capture_output=True)  # nosec B603 B607


def _repo(path: Path, commits: int = 5) -> Path:
    """A git repo where ``a.py`` has *commits* commits (churn = *commits*)."""
    path.mkdir()
    _run(path, "init", "-q")
    # Cut of the actionable hotspot = min score (50): no dependence on the project percentile.
    (path / "debtector.toml").write_text(
        "[audit.thresholds]\nhotspot_percentile = 1\n", encoding="utf-8"
    )
    # A second file with history and no complexity, so the cut is not just the one score.
    (path / "b.py").write_text("y = 0\n", encoding="utf-8")
    for i in range(commits):
        (path / "a.py").write_text(f"x = {i}\n", encoding="utf-8")
        _run(path, "add", ".")
        _run(path, "commit", "-q", "-m", f"c{i}")
    return path


def _diff(project: Path, base_cx: int, pr_cx: int, capsys) -> dict:
    configure_logging(project=str(project))
    base = _index(project.parent / "base.db", {"a.py": {"f": base_cx}, "b.py": {}})
    pr = _index(project.parent / "pr.db", {"a.py": {"f": pr_cx}, "b.py": {}})
    cmd_diff(argparse.Namespace(project=str(project), json=True, db_base=base, db_pr=pr))
    return json.loads(capsys.readouterr().out)


def test_E20_file_above_the_cut_only_in_the_pr_is_a_new_hotspot(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path / "repo")
    # churn 5: base 5 x 5 = 25 (below the cut of 50), PR 5 x 12 = 60.
    result = _diff(repo, 5, 12, capsys)
    assert result["new_hotspots"] == [
        {
            "file_path": "a.py",
            "churn": 5,
            "complexity": 12,
            "hotspot_score": 60,
            "severity": "medium",
        }
    ]
    assert result["worsened_hotspots"] == []
    assert result["skipped"] == []


def test_E21_medium_hotspot_that_becomes_high_is_worsened(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path / "repo")
    # churn 5: base 60 (medium), PR 5 x 40 = 200 (>= 3 x 50: high).
    result = _diff(repo, 12, 40, capsys)
    assert result["worsened_hotspots"] == [
        {
            "file_path": "a.py",
            "churn": 5,
            "complexity_before": 12,
            "complexity_after": 40,
            "severity_before": "medium",
            "severity": "high",
        }
    ]
    assert result["new_hotspots"] == []


def test_E20_same_severity_and_hotspots_gone_are_not_reported(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path / "repo")
    result = _diff(repo, 12, 20, capsys)
    assert result["new_hotspots"] == result["worsened_hotspots"] == []
    result = _diff(repo, 12, 2, capsys)
    assert result["new_hotspots"] == result["worsened_hotspots"] == []


def test_E22_shallow_clone_skips_hotspots_and_keeps_the_rest(tmp_path: Path, capsys) -> None:
    origin = _repo(tmp_path / "origin")
    clone = tmp_path / "clone"
    subprocess.run(  # nosec B603 B607
        ["git", "clone", "-q", "--depth", "1", origin.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    result = _diff(clone, 5, 30, capsys)
    assert [s["section"] for s in result["skipped"]] == ["hotspots"]
    assert "shallow" in result["skipped"][0]["reason"]
    assert result["new_hotspots"] == result["worsened_hotspots"] == []
    assert [f["qualified_name"] for f in result["worsened_functions"]] == ["a.py::f"]


def test_text_output_lists_hotspots_and_skipped(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path / "repo")
    configure_logging(project=str(repo))
    base = _index(tmp_path / "base.db", {"a.py": {"f": 5}})
    pr = _index(tmp_path / "pr.db", {"a.py": {"f": 12}})
    cmd_diff(argparse.Namespace(project=str(repo), json=False, db_base=base, db_pr=pr))
    out = capsys.readouterr().out
    assert "New hotspots (1):" in out
    assert "a.py: churn 5, complexity 12 (medium)" in out


def test_churn_is_read_from_the_indexed_subdirectory(tmp_path: Path, capsys) -> None:
    """``debtector index src``: graph paths are relative to ``src``, and so must the churn be."""
    from debtector.graph_store import GraphStore

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    (repo / "debtector.toml").write_text(
        "[audit.thresholds]\nhotspot_percentile = 1\n", encoding="utf-8"
    )
    (repo / "src").mkdir()
    (repo / "src" / "b.py").write_text("y = 0\n", encoding="utf-8")
    for i in range(5):
        (repo / "src" / "a.py").write_text(f"x = {i}\n", encoding="utf-8")
        _run(repo, "add", ".")
        _run(repo, "commit", "-q", "-m", f"c{i}")
    configure_logging(project=str(repo))
    dbs = []
    for name, cx in (("base", 5), ("pr", 12)):
        db = _index(tmp_path / f"{name}.db", {"a.py": {"f": cx}, "b.py": {}})
        store = GraphStore(db)
        store.set_metadata("index_root", "src")
        store.close()
        dbs.append(db)

    cmd_diff(argparse.Namespace(project=str(repo), json=True, db_base=dbs[0], db_pr=dbs[1]))

    result = json.loads(capsys.readouterr().out)
    assert [h["file_path"] for h in result["new_hotspots"]] == ["a.py"]
