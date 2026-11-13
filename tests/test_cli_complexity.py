"""Tests for ``debtector complexity``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from debtector.cli.app import main
from debtector.cli.graph import cmd_index
from debtector.cli.quality import cmd_complexity

SRC = """\
def simple():
    return 1


def branchy(a, b):
    if a and b:
        return 1
    for x in a:
        if x:
            return x
    return 0


class Box:
    def mid(self, a):
        return 1 if a else 2
"""


@pytest.fixture()
def project(tmp_path: Path) -> str:
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text(SRC, encoding="utf-8")
    cmd_index(argparse.Namespace(project=str(tmp_path), path=str(src), json=True))
    return str(tmp_path)


def _args(project: str, **kwargs) -> argparse.Namespace:
    defaults = {"project": project, "json": False, "limit": None, "min": 0}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _json(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_json_shape_and_order(project: str, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()

    cmd_complexity(_args(project, json=True))

    data = _json(capsys)
    assert list(data) == ["functions"]
    entries = data["functions"]
    assert all(
        set(e) == {"qualified_name", "kind", "complexity", "file_path", "line"} for e in entries
    )
    assert [(e["qualified_name"], e["complexity"]) for e in entries] == [
        ("mod.py::branchy", 5),
        ("mod.py::Box.mid", 2),
        ("mod.py::simple", 1),
    ]
    assert entries[0]["kind"] == "Function"
    assert entries[0]["file_path"] == "mod.py"
    assert entries[0]["line"] == 5


def test_limit_and_min(project: str, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()

    cmd_complexity(_args(project, json=True, limit=1))
    assert [e["qualified_name"] for e in _json(capsys)["functions"]] == ["mod.py::branchy"]

    cmd_complexity(_args(project, json=True, min=2))
    assert {e["qualified_name"] for e in _json(capsys)["functions"]} == {
        "mod.py::branchy",
        "mod.py::Box.mid",
    }


def test_text_output(project: str, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()

    cmd_complexity(_args(project))

    out = capsys.readouterr().out
    assert "mod.py::branchy" in out
    assert "mod.py:5" in out
    assert out.index("branchy") < out.index("Box.mid") < out.index("simple")


@pytest.mark.parametrize("position", ["before", "after"])
def test_main_json_flag_before_or_after_subcommand(
    project: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    position: str,
) -> None:
    capsys.readouterr()
    argv = ["debtector", "--project", project]
    if position == "before":
        argv += ["--json", "complexity", "--limit", "1", "--min", "2"]
    else:
        argv += ["complexity", "--limit", "1", "--min", "2", "--json"]
    monkeypatch.setattr(sys, "argv", argv)

    main()

    assert [e["qualified_name"] for e in _json(capsys)["functions"]] == ["mod.py::branchy"]
