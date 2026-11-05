"""End-to-end tests of the calibrated health score (version 2) on real repos.

Gherkin contract:

    Given un repo con un hub importado por 10 módulos y un único autor
    When se ejecuta ``audit``
    Then ``critical_knowledge_concentration`` lista el hub pero no penaliza el score

    Given el mismo repo con un segundo autor en el historial
    Then el hub (bus factor 1, Ca alto) sí penaliza el score
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — tests drive a local throwaway repo
from pathlib import Path

import pytest

from debtector.cli import cmd_audit, cmd_index
from debtector.git_history import list_authors
from debtector.logging import configure_logging

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

_N_IMPORTERS = 10  # == DEFAULT_HIGH_CA, so the hub is "critical knowledge" with bus factor 1


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _git(repo: Path, *args: str, author: str = "Alice") -> None:
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", "-c", f"user.name={author}", "-c", f"user.email={author}@x.io", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _commit(repo: Path, files: dict[str, str], author: str = "Alice") -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A", author=author)
    _git(repo, "commit", "-q", "-m", "change", author=author)


def _make_repo(base: Path, second_author: bool, other_path_author: bool = False) -> Path:
    repo = base / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    files = {"src/hub.py": "def f():\n    return 1\n"}
    for i in range(_N_IMPORTERS):
        files[f"src/m{i}.py"] = f"from hub import f\n\n\ndef g{i}():\n    return f()\n"
    _commit(repo, files)
    if second_author:
        touched = "# touched\nfrom hub import f\n\n\ndef g0():\n    return f()\n"
        _commit(repo, {"src/m0.py": touched}, "Bob")
    if other_path_author:
        _commit(repo, {"docs/notes.txt": "notes\n"}, "Bob")
    return repo


def _audit(repo: Path, capsys: pytest.CaptureFixture[str]) -> dict:
    cmd_index(argparse.Namespace(project=str(repo), path=str(repo / "src"), json=True))
    capsys.readouterr()
    cmd_audit(argparse.Namespace(project=str(repo), top_n=10, full=False, json=True))
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_list_authors_single_and_multiple(tmp_path: Path) -> None:
    single = _make_repo(tmp_path / "a", second_author=False)
    multi = _make_repo(tmp_path / "b", second_author=True)

    assert list_authors(single) == {"Alice"}
    assert list_authors(multi) == {"Alice", "Bob"}


def test_single_author_knowledge_concentration_is_not_scored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _audit(_make_repo(tmp_path, second_author=False), capsys)

    assert "hub.py" in out["testRisk"]["critical_knowledge_concentration"]  # section unchanged
    assert any(b["file_path"] == "hub.py" for b in out["busFactor"])
    assert out["summary"]["health_score"] == 100


def test_multi_author_knowledge_concentration_is_scored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _audit(_make_repo(tmp_path, second_author=True), capsys)

    assert "hub.py" in out["testRisk"]["critical_knowledge_concentration"]
    # 1 critical over 11 modules: 100 - 100 * 15 / 55 = 72.7 -> 73 (no hotspot is actionable)
    assert out["summary"]["health_score"] == 73


def test_summary_carries_health_score_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _audit(_make_repo(tmp_path, second_author=False), capsys)

    assert out["summary"]["health_score_version"] == 2
    assert out["schema_version"] == 1


def test_config_thresholds_reach_the_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path, second_author=True)
    (repo / "debtector.toml").write_text(
        "[audit.thresholds]\ntestrisk_high_ca = 100\n", encoding="utf-8"
    )

    out = _audit(repo, capsys)

    assert out["testRisk"]["critical_knowledge_concentration"] == []
    assert out["summary"]["health_score"] == 100


def test_hotspot_config_reaches_the_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path, second_author=False)
    (repo / "debtector.toml").write_text(
        "[audit.thresholds]\nhotspot_percentile = 90\nhotspot_min_score = 5\n", encoding="utf-8"
    )

    out = _audit(repo, capsys)

    # The hub (churn 1 x coupling 10) is now actionable: 1 medium over 11 modules
    # -> 100 - 100 * 2 / 55 = 96.4 -> 96
    assert out["summary"]["health_score"] == 96


def test_author_elsewhere_in_the_repo_counts_as_multi_author(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Alice wrote all of src/, Bob only touched docs/: the repo has two authors."""
    repo = _make_repo(tmp_path, second_author=False, other_path_author=True)

    assert list_authors(repo / "src") == {"Alice", "Bob"}
    out = _audit(repo, capsys)
    assert "hub.py" in out["testRisk"]["critical_knowledge_concentration"]
    assert out["summary"]["health_score"] == 73


def test_bot_authors_are_ignored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """One human plus a `[bot]` account is still a single-author repository."""
    repo = _make_repo(tmp_path, second_author=False)
    _commit(repo, {"docs/bump.txt": "v2\n"}, "github-actions[bot]")

    assert list_authors(repo) == {"Alice"}
    out = _audit(repo, capsys)
    assert "hub.py" in out["testRisk"]["critical_knowledge_concentration"]
    assert out["summary"]["health_score"] == 100


def test_shallow_clone_never_gets_the_single_author_exemption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A depth-1 clone only sees the last commit: authorship is unknown, findings are scored."""
    origin = _make_repo(tmp_path / "origin", second_author=True)
    clone = tmp_path / "clone"
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(clone)],
        check=True,
        capture_output=True,
    )

    assert list_authors(clone) == {"Bob"}  # all a shallow history shows
    out = _audit(clone, capsys)

    assert "hub.py" in out["testRisk"]["critical_knowledge_concentration"]
    assert out["summary"]["health_score"] == 73
