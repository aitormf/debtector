"""Tests for the severity of actionable hotspots (D-0007).

Gherkin contract:
    Given los hotspots accionables de un proyecto
    When se les asigna severidad
    Then es ``high`` si el score llega a ``hotspot_high_factor`` x el corte y ``medium`` si no
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — tests drive a local throwaway repo
from pathlib import Path

import pytest

from debtector.audit.health_score import select_actionable_hotspots
from debtector.cli import cmd_index
from debtector.cli.quality import cmd_audit
from debtector.config import load_config
from debtector.git_history import HotspotMetrics
from debtector.logging import configure_logging


def _hotspots(scores: list[float]) -> list[HotspotMetrics]:
    return [
        HotspotMetrics(file_path=f"m{i}.py", churn=1, coupling=s, hotspot_score=s)
        for i, s in enumerate(scores)
    ]


def _severities(result: list[HotspotMetrics]) -> dict[float, str]:
    return {h.hotspot_score: h.severity for h in result}


def test_E11_far_above_the_cut_is_high_and_at_the_cut_is_medium() -> None:
    # D-0007
    hs = _hotspots([1.0, 2574.0, 12848.0])
    result = select_actionable_hotspots(hs, percentile=1, min_score=2574, high_factor=3)
    assert _severities(result) == {2574.0: "medium", 12848.0: "high"}


def test_E12_exactly_factor_times_the_cut_is_high() -> None:
    hs = _hotspots([1.0, 50.0, 150.0, 149.0])
    result = select_actionable_hotspots(hs, percentile=1, min_score=50, high_factor=3)
    assert _severities(result) == {50.0: "medium", 149.0: "medium", 150.0: "high"}


def test_E13_a_single_hotspot_equal_to_the_cut_is_medium() -> None:
    result = select_actionable_hotspots(
        _hotspots([60.0]), percentile=90, min_score=50, high_factor=3
    )
    assert _severities(result) == {60.0: "medium"}


def test_E11_high_factor_defaults_to_3() -> None:
    result = select_actionable_hotspots(_hotspots([1.0, 50.0, 150.0]), percentile=1, min_score=50)
    assert _severities(result) == {50.0: "medium", 150.0: "high"}


@pytest.mark.parametrize("bad", ["0", "-1", "'x'", "true"])
def test_E11_invalid_high_factor_is_a_config_error(tmp_path: Path, bad: str) -> None:
    (tmp_path / "debtector.toml").write_text(
        f"[audit.thresholds]\nhotspot_high_factor = {bad}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hotspot_high_factor"):
        load_config(str(tmp_path))


def test_E11_high_factor_default_is_3(tmp_path: Path) -> None:
    assert load_config(str(tmp_path)).audit.hotspot_high_factor == 3


# ---------------------------------------------------------------- end to end


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", "-c", "user.name=Alice", "-c", "user.email=a@x.io", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _commit(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_E14_json_audit_reports_hotspot_severity_and_version_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(project=str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for i in range(4):  # 4 commits each: big.py complexity 4 -> 16, small.py complexity 2 -> 8
        _commit(
            repo,
            {
                "big.py": f"def f(a, b, c):\n    if a and b and c:\n        return {i}\n",
                "small.py": f"def g(a):\n    if a:\n        return {i}\n",
            },
        )
    _commit(repo, {"tiny.py": "def h():\n    return 1\n"})  # keeps p1 below min_score
    (repo / "debtector.toml").write_text(
        "[audit.thresholds]\nhotspot_percentile = 1\nhotspot_min_score = 5\n", encoding="utf-8"
    )
    cmd_index(argparse.Namespace(project=str(repo), path=str(repo), json=True))
    capsys.readouterr()
    cmd_audit(argparse.Namespace(project=str(repo), top_n=10, full=False, json=True))
    out = json.loads(capsys.readouterr().out)
    sev = {h["file_path"]: h["severity"] for h in out["hotspots"]}
    assert sev == {"big.py": "high", "small.py": "medium", "tiny.py": None}
    assert out["summary"]["health_score_version"] == 5
