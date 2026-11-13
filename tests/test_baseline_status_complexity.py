"""``baseline status`` compares complexity with the baseline (D-0010, D-0019)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from test_baseline_complexity import _seed

from debtector import metrics as _metrics
from debtector.cli.baseline import cmd_baseline
from debtector.logging import configure_logging


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _baseline(project: Path, complexity: dict | None) -> None:
    snapshot: dict = {
        "metrics_version": _metrics.METRICS_VERSION,
        "modules": [],
        "cycles": [],
        "god_modules": [],
        "sdp_violations": [],
    }
    if complexity is not None:
        snapshot["complexity"] = complexity
    path = project / ".debtector" / "baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot), encoding="utf-8")


def _status(
    project: Path, capsys, severity: str | None = None, medium: int | None = None, **extra
) -> tuple[int, str]:
    lines = []
    if severity:
        lines.append(f'[metrics.severity]\ncomplexity = "{severity}"\n')
    if medium:
        lines.append(f"[audit.thresholds]\ncomplexity_medium = {medium}\n")
    if lines:
        (project / "debtector.toml").write_text("\n".join(lines), encoding="utf-8")
    args = argparse.Namespace(
        project=str(project), baseline_cmd="status", **{"json": False, "reporter": None, **extra}
    )
    code = 0
    try:
        cmd_baseline(args)
    except SystemExit as e:
        code = int(e.code or 0)
    return code, capsys.readouterr().out


def test_E9_worsened_function_is_a_regression(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 30}})
    _baseline(tmp_path, {"medium": 21, "functions": {"src/a.py::g": 25}})
    _, out = _status(tmp_path, capsys, json=True)
    regs = json.loads(out)["complexity_regressions"]
    assert [(r["qualified_name"], r["before"], r["after"]) for r in regs] == [
        ("src/a.py::g", 25, 30)
    ]


def test_E10_unchanged_function_is_not_reported(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 25}})
    _baseline(tmp_path, {"medium": 21, "functions": {"src/a.py::g": 25}})
    code, out = _status(tmp_path, capsys, "error")
    assert code == 0
    assert "No changes from baseline" in out


def test_E11_new_function_above_medium_is_a_regression(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 25, "k": 22}})
    _baseline(tmp_path, {"medium": 21, "functions": {"src/a.py::g": 25}})
    _, out = _status(tmp_path, capsys, json=True)
    regs = json.loads(out)["complexity_regressions"]
    assert [(r["qualified_name"], r["before"], r["after"]) for r in regs] == [
        ("src/a.py::k", None, 22)
    ]


def test_E12_function_that_crossed_the_threshold_is_a_regression(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"m": 24}})
    _baseline(tmp_path, {"medium": 21, "functions": {}})
    _, out = _status(tmp_path, capsys, json=True)
    assert [r["qualified_name"] for r in json.loads(out)["complexity_regressions"]] == [
        "src/a.py::m"
    ]


def test_E13_error_blocks_and_warning_does_not(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 30}})
    _baseline(tmp_path, {"medium": 21, "functions": {"src/a.py::g": 25}})
    code, out = _status(tmp_path, capsys, "error")
    assert code == 1
    assert "src/a.py::g" in out
    code, out = _status(tmp_path, capsys, "warning")
    assert code == 0
    assert "src/a.py::g" in out


def test_E14_old_baseline_skips_complexity_and_warns(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 40}})
    _baseline(tmp_path, None)
    code, out = _status(tmp_path, capsys, "error")
    assert code == 0
    assert "baseline save" in out
    assert "src/a.py::g" not in out


def test_E15_different_medium_skips_complexity_and_warns(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 40}})
    _baseline(tmp_path, {"medium": 21, "functions": {}})
    code, out = _status(tmp_path, capsys, "error", medium=15)
    assert code == 0
    assert "baseline save" in out
    assert "src/a.py::g" not in out


def test_E16_reporters_emit_complexity_regressions(tmp_path: Path, capsys) -> None:
    _seed(str(tmp_path), {"src/a.py": {"g": 30}})
    _baseline(tmp_path, {"medium": 21, "functions": {"src/a.py::g": 25}})
    _, out = _status(tmp_path, capsys, "error", reporter="github")
    assert "::error file=src/a.py," in out and "25 → 30" in out
    _, out = _status(tmp_path, capsys, reporter="gitlab")
    assert "[ERROR]" in out and "src/a.py::g" in out
