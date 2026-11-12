"""Markdown output of ``debtector diff`` for PR comments (pr-diff, T6)."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_diff_complexity import _index

from debtector.cli import cmd_diff
from debtector.logging import configure_logging
from debtector.render.diff_markdown import MARKER, render_diff_markdown


def _empty() -> dict:
    keys = (
        "new_cycles resolved_cycles new_god_modules resolved_god_modules new_sdp_violations "
        "resolved_sdp_violations instability_regressions worsened_functions improved_functions "
        "new_hotspots worsened_hotspots skipped"
    )
    return {k: [] for k in keys.split()}


def _fn(name: str, before: int, after: int) -> dict:
    return {"qualified_name": name, "file_path": "a.py", "before": before, "after": after}


def test_E23_empty_diff_is_one_line() -> None:
    lines = render_diff_markdown(_empty()).splitlines()
    assert lines[-1] == "✅ debtector: no architectural changes"
    assert len([line for line in lines if line.strip()]) == 2  # marker + the line


def test_E24_starts_with_hidden_marker() -> None:
    assert MARKER == "<!-- debtector-diff -->"
    assert render_diff_markdown(_empty()).startswith("<!-- debtector-diff -->\n")
    result = _empty()
    result["worsened_functions"] = [_fn("a.py::f", 10, 20)]
    assert render_diff_markdown(result).startswith("<!-- debtector-diff -->\n")


def test_E25_sections_capped_at_20_rows() -> None:
    result = _empty()
    result["worsened_functions"] = [_fn(f"a.py::f{i}", 10, 30) for i in range(60)]
    out = render_diff_markdown(result)
    assert out.count("a.py::f") == 20
    assert "…and 40 more" in out


def test_E26_special_characters_are_escaped() -> None:
    result = _empty()
    result["worsened_functions"] = [_fn("a.py::x|<script>`y`", 10, 30)]
    out = render_diff_markdown(result)
    row = next(line for line in out.splitlines() if "script" in line)
    assert "<script>" not in out
    assert "&lt;script&gt;" in row
    assert "\\|" in row
    assert "`y`" not in row
    # the row still has exactly the unescaped pipes of its own columns
    assert row.replace("\\|", "").count("|") == 4


def test_all_sections_are_rendered() -> None:
    result = _empty()
    result["new_cycles"] = [["a.py", "b.py"]]
    result["new_god_modules"] = ["g.py"]
    result["new_sdp_violations"] = [{"source": "s.py", "target": "t.py"}]
    result["instability_regressions"] = [
        {"file_path": "i.py", "metric": "instability", "before": 0.1, "after": 0.5}
    ]
    result["new_hotspots"] = [
        {"file_path": "h.py", "churn": 3, "complexity": 40, "severity": "high", "hotspot_score": 1}
    ]
    result["skipped"] = [{"section": "hotspots", "reason": "shallow clone"}]
    out = render_diff_markdown(result)
    for text in ("New cycles", "a.py", "g.py", "s.py", "i.py", "h.py", "shallow clone"):
        assert text in out


def test_worsened_hotspot_shows_before_and_after() -> None:
    result = _empty()
    result["worsened_hotspots"] = [
        {
            "file_path": "h.py",
            "churn": 3,
            "complexity_before": 20,
            "complexity_after": 40,
            "severity_before": "medium",
            "severity": "high",
        }
    ]
    assert "20 → 40 (medium → high)" in render_diff_markdown(result)


def test_E24_cli_format_markdown(tmp_path: Path, capsys) -> None:
    configure_logging(project=str(tmp_path))
    base = _index(tmp_path / "base.db", {"a.py": {"f": 18}})
    pr = _index(tmp_path / "pr.db", {"a.py": {"f": 22}})
    cmd_diff(
        argparse.Namespace(
            project=str(tmp_path), json=False, format="markdown", db_base=base, db_pr=pr
        )
    )
    out = capsys.readouterr().out
    assert out.startswith("<!-- debtector-diff -->\n")
    assert "a.py::f" in out


def _row_for(name: str) -> str:
    result = _empty()
    result["worsened_functions"] = [_fn(name, 10, 30)]
    return render_diff_markdown(result).splitlines()[-1]


def test_markdown_syntax_in_names_stays_literal() -> None:
    """``__init__.py`` must not turn bold, nor ``![x](i.png)`` into an image."""
    assert "src/\\_\\_init\\_\\_.py::f" in _row_for("src/__init__.py::f")
    assert "\\!\\[x\\]\\(i.png\\).py::f" in _row_for("![x](i.png).py::f")


def test_existing_backslash_cannot_cancel_an_escape() -> None:
    """``a\\`` before a backtick: the backslash itself is escaped first."""
    assert "a\\\\\\`b" in _row_for("a\\`b")
