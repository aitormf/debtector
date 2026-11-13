"""``[metrics.severity] complexity`` decides whether ``debtector diff`` blocks (D-0019)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from test_diff_complexity import _index

from debtector.cli.pr_diff import cmd_diff
from debtector.config import Severity, load_config
from debtector.logging import configure_logging


def _run(tmp_path: Path, capsys, base: dict, pr: dict, severity: str | None) -> tuple[int, dict]:
    configure_logging(project=str(tmp_path))
    if severity is not None:
        (tmp_path / "debtector.toml").write_text(
            f'[metrics.severity]\ncomplexity = "{severity}"\n', encoding="utf-8"
        )
    db_base = _index(tmp_path / "base.db", base)
    db_pr = _index(tmp_path / "pr.db", pr)
    args = argparse.Namespace(project=str(tmp_path), json=True, db_base=db_base, db_pr=db_pr)
    code = 0
    try:
        cmd_diff(args)
    except SystemExit as e:
        code = int(e.code or 0)
    return code, json.loads(capsys.readouterr().out)


def test_E1_default_lists_worsened_function_and_exits_0(tmp_path: Path, capsys) -> None:
    code, out = _run(tmp_path, capsys, {"a.py": {}}, {"a.py": {"f": 40}}, None)
    assert [w["qualified_name"] for w in out["worsened_functions"]] == ["a.py::f"]
    assert code == 0


def test_E2_error_severity_blocks_on_worsened_function(tmp_path: Path, capsys) -> None:
    code, _ = _run(tmp_path, capsys, {"a.py": {}}, {"a.py": {"f": 40}}, "error")
    assert code == 1


def test_E3_improvement_never_blocks(tmp_path: Path, capsys) -> None:
    code, out = _run(tmp_path, capsys, {"a.py": {"f": 35}}, {"a.py": {"f": 10}}, "error")
    assert out["improved_functions"]
    assert code == 0


def test_E4_growth_below_medium_does_not_block(tmp_path: Path, capsys) -> None:
    code, _ = _run(tmp_path, capsys, {"a.py": {"f": 12}}, {"a.py": {"f": 18}}, "error")
    assert code == 0


def test_E5_info_still_lists_and_exits_0(tmp_path: Path, capsys) -> None:
    code, out = _run(tmp_path, capsys, {"a.py": {}}, {"a.py": {"f": 40}}, "info")
    assert out["worsened_functions"]
    assert code == 0


def test_E6_invalid_complexity_severity_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "debtector.toml").write_text(
        '[metrics.severity]\ncomplexity = "bogus"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="severity"):
        load_config(tmp_path)


def test_E1_default_complexity_severity_is_warning(tmp_path: Path) -> None:
    assert load_config(tmp_path).metrics.severity.complexity == Severity.WARNING
