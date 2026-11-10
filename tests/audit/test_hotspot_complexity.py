"""Audit hotspots are ranked by churn x cyclomatic complexity.

Gherkin contract:
    Given a repo whose ``hot.py`` has a branchy function and changes in every commit
    When ``audit`` runs
    Then its hotspot entry reports churn, complexity and score = churn x complexity
    And ``summary.health_score_version`` is 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — tests drive a local throwaway repo
from pathlib import Path

import pytest

from debtector.cli import cmd_audit, cmd_index
from debtector.logging import configure_logging

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

_COMMITS = 4


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", "-c", "user.name=Dev", "-c", "user.email=dev@x.io", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    configure_logging(project=str(tmp_path))
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    _git(root, "init", "-q")
    for i in range(_COMMITS):
        (root / "src" / "hot.py").write_text(
            f"def decide(a, b):\n    if a and b:\n        return {i}\n"
            "    for x in a:\n        if x:\n            return x\n    return None\n",
            encoding="utf-8",
        )
        (root / "src" / "flat.py").write_text(f"X = {i}\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", f"change {i}")
    return root


def test_audit_hotspot_entry_reports_complexity_and_score(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_index(argparse.Namespace(project=str(repo), path=str(repo / "src"), json=True))
    capsys.readouterr()

    cmd_audit(argparse.Namespace(project=str(repo), top_n=10, full=False, json=True))

    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["summary"]["health_score_version"] == 5
    # flat.py has no functions: complexity 0, score 0, so it is not listed
    assert out["hotspots"] == [
        {
            "file_path": "hot.py",
            "churn": _COMMITS,
            "complexity": 5,
            "score": _COMMITS * 5.0,
            "severity": None,
        }
    ]
