"""Text output of the function-complexity sections of ``debtector diff`` (pr-diff, T4)."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_diff_complexity import _index

from debtector.cli.pr_diff import cmd_diff
from debtector.logging import configure_logging


def test_text_output_lists_worsened_function(tmp_path: Path, capsys) -> None:
    configure_logging(project=str(tmp_path))
    base = _index(tmp_path / "base.db", {"a.py": {"f": 18}})
    pr = _index(tmp_path / "pr.db", {"a.py": {"f": 22}})
    cmd_diff(argparse.Namespace(project=str(tmp_path), json=False, db_base=base, db_pr=pr))
    out = capsys.readouterr().out
    assert "Functions with worse complexity (1):" in out
    assert "a.py::f: 18 → 22" in out


def test_configured_test_paths_are_excluded(tmp_path: Path, capsys) -> None:
    """A function under a ``test_paths`` directory of debtector.toml is a test, not production."""
    import json

    configure_logging(project=str(tmp_path))
    (tmp_path / "debtector.toml").write_text('test_paths = ["checks"]\n', encoding="utf-8")
    base = _index(tmp_path / "base.db", {"checks/x.py": {}})
    pr = _index(tmp_path / "pr.db", {"checks/x.py": {"verify": 40}})
    cmd_diff(argparse.Namespace(project=str(tmp_path), json=True, db_base=base, db_pr=pr))
    assert json.loads(capsys.readouterr().out)["worsened_functions"] == []
