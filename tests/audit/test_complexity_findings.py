"""Function complexity scores in the health score (D-0006).

Gherkin contract:
    Given production functions and methods with a cyclomatic complexity
    When ``audit`` runs
    Then complexity >= complexity_high is a ``high`` finding, >= complexity_medium
    a ``medium`` one, test-file functions never count, and the JSON has a
    ``complexity`` section with ``summary.health_score_version`` 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — tests drive a local throwaway repo
from pathlib import Path

import pytest

from debtector.audit.complexity import select_complexity_findings
from debtector.cli import cmd_audit, cmd_index
from debtector.config import load_config
from debtector.logging import configure_logging
from debtector.models import GraphNode

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _node(name: str, complexity: int, file_path: str = "src/a.py", kind: str = "Function"):
    return GraphNode(
        id=1,
        kind=kind,
        name=name,
        qualified_name=f"{file_path}::{name}",
        file_path=file_path,
        line_start=7,
        line_end=9,
        language="python",
        parent_name=None,
        signature=None,
        docstring=None,
        file_hash=None,
        extra={"complexity": complexity},
    )


def _select(nodes, medium=21, high=31, is_test=lambda p: p.startswith("tests/")):
    return select_complexity_findings(nodes, medium=medium, high=high, is_test=is_test)


def test_E4_complexity_below_medium_has_no_finding() -> None:
    assert _select([_node("f", 20)]) == []


def test_E5_complexity_21_is_medium() -> None:
    (finding,) = _select([_node("f", 21)])
    assert (finding.severity, finding.complexity, finding.line) == ("medium", 21, 7)
    assert finding.qualified_name == "src/a.py::f"
    assert finding.file_path == "src/a.py"


def test_E6_complexity_30_is_medium_and_31_is_high() -> None:
    findings = _select([_node("a", 30), _node("b", 31, kind="Method")])
    assert [(f.qualified_name, f.severity) for f in findings] == [
        ("src/a.py::b", "high"),
        ("src/a.py::a", "medium"),
    ]


def test_E7_custom_medium_threshold() -> None:
    (finding,) = _select([_node("f", 11)], medium=11)
    assert finding.severity == "medium"


def test_E8_medium_above_high_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "debtector.toml").write_text(
        "[audit.thresholds]\ncomplexity_medium = 40\ncomplexity_high = 30\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="complexity_medium"):
        load_config(tmp_path)


def test_E8_complexity_thresholds_default_and_validate(tmp_path: Path) -> None:
    thr = load_config(tmp_path).audit
    assert (thr.complexity_medium, thr.complexity_high) == (21, 31)
    (tmp_path / "debtector.toml").write_text(
        "[audit.thresholds]\ncomplexity_high = -1\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="complexity_high"):
        load_config(tmp_path)


def test_E9_test_file_functions_never_count() -> None:
    nodes = [_node("t", 50, file_path="tests/test_a.py"), _node("x", 50, file_path="../ext/t.py")]
    assert _select(nodes) == []


def test_functions_without_complexity_are_ignored() -> None:
    node = _node("f", 0)
    node.extra = {}
    assert _select([node]) == []


# ── end to end ──────────────────────────────────────────────────────────────


def _branchy(name: str, complexity: int) -> str:
    body = "    if a:\n        pass\n" * (complexity - 1)
    return f"def {name}(a):\n{body}    return a\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 — fixed arguments, throwaway repo
        ["git", "-c", "user.name=Dev", "-c", "user.email=dev@x.io", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _audit(tmp_path: Path, files: dict[str, str], capsys, json_out: bool = True):
    configure_logging(project=str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    cmd_index(argparse.Namespace(project=str(root), path=str(root), json=True))
    capsys.readouterr()
    cmd_audit(argparse.Namespace(project=str(root), top_n=10, full=False, json=json_out))
    out = capsys.readouterr().out
    return json.loads(out.strip().splitlines()[-1]) if json_out else out


@needs_git
def test_E10_json_has_complexity_section_and_version_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _audit(
        tmp_path,
        {
            "src/big.py": _branchy("huge", 31) + _branchy("mid", 25) + _branchy("ok", 20),
            "src/other.py": "X = 1\n",
            "tests/test_big.py": _branchy("test_huge", 50),
        },
        capsys,
    )
    assert out["summary"]["health_score_version"] == 4
    entries = {e["qualified_name"]: e for e in out["complexity"]}
    assert set(entries) == {"src/big.py::huge", "src/big.py::mid"}  # E9: test file excluded
    assert entries["src/big.py::huge"] == {
        "qualified_name": "src/big.py::huge",
        "file_path": "src/big.py",
        "line": 1,
        "complexity": 31,
        "severity": "high",
    }
    assert entries["src/big.py::mid"]["severity"] == "medium"
    assert out["complexity"][0]["severity"] == "high"  # worst first


@needs_git
def test_E10_complexity_findings_lower_the_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _audit(tmp_path, {"src/big.py": _branchy("huge", 31), "src/other.py": "X = 1\n"}, capsys)
    # 1 high over 2 modules: 100 - 100 * 5 / 10 = 50
    assert out["summary"]["health_score"] == 50


@needs_git
def test_E10_text_output_lists_complexity_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _audit(tmp_path, {"src/big.py": _branchy("huge", 31)}, capsys, json_out=False)
    assert "src/big.py::huge" in text
    assert "complexity" in text.lower()
