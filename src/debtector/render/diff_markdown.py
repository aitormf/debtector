"""Markdown rendering of the architectural diff, for PR comments (pr-diff R6)."""

from __future__ import annotations

import html

MARKER = "<!-- debtector-diff -->"
MAX_ROWS = 20


def _cycle(item: list[str]) -> tuple:
    return (" → ".join(item) + " → ...",)


def _sdp(item: dict) -> tuple:
    return item["source"], item["target"]


def _change(item: dict) -> tuple:
    return item["file_path"], item["before"], item["after"]


def _function(item: dict) -> tuple:
    return item["qualified_name"], item["before"], item["after"]


def _new_hotspot(item: dict) -> tuple:
    return item["file_path"], item["churn"], f"{item['complexity']} ({item['severity']})"


def _worsened_hotspot(item: dict) -> tuple:
    return (
        item["file_path"],
        item["churn"],
        f"{item['complexity_before']} → {item['complexity_after']} "
        f"({item['severity_before']} → {item['severity']})",
    )


# (result key, title, column headers, row builder)
_SECTIONS = (
    ("new_cycles", "New cycles", ("Cycle",), _cycle),
    ("resolved_cycles", "Resolved cycles", ("Cycle",), _cycle),
    ("new_god_modules", "New god modules", ("Module",), lambda i: (i,)),
    ("resolved_god_modules", "Resolved god modules", ("Module",), lambda i: (i,)),
    ("new_sdp_violations", "New SDP violations", ("Source", "Target"), _sdp),
    ("resolved_sdp_violations", "Resolved SDP violations", ("Source", "Target"), _sdp),
    ("instability_regressions", "Instability regressions", ("Module", "Before", "After"), _change),
    (
        "worsened_functions",
        "Functions with worse complexity",
        ("Function", "Before", "After"),
        _function,
    ),
    (
        "improved_functions",
        "Functions with better complexity",
        ("Function", "Before", "After"),
        _function,
    ),
    ("new_hotspots", "New hotspots", ("File", "Churn", "Complexity"), _new_hotspot),
    ("worsened_hotspots", "Worsened hotspots", ("File", "Churn", "Complexity"), _worsened_hotspot),
)


# Markdown punctuation that can change how a name renders: emphasis, links and images
# (escaping the brackets is enough), code spans and table pipes. The backslash goes first,
# so an existing one cannot cancel an escape.
_MD_SPECIAL = "\\`*_[]!|~"


def _escape(value: object) -> str:
    """Make *value* literal inside a table cell: no Markdown, no HTML, one line."""
    text = "".join("\\" + c if c in _MD_SPECIAL else c for c in str(value))
    return html.escape(text, quote=False).replace("\n", " ")


def _row(cells: tuple) -> str:
    return "| " + " | ".join(_escape(c) for c in cells) + " |"


def render_diff_markdown(result: dict) -> str:
    """Render the output of ``compute_diff`` as a PR comment.

    Args:
        result: Output of :func:`debtector.diff.compute_diff`.

    Returns:
        Markdown starting with the hidden :data:`MARKER`, with a table per non-empty
        section capped at :data:`MAX_ROWS` rows.
    """
    parts = [MARKER]
    sections = [s for s in _SECTIONS if result.get(s[0])]
    if not sections:
        parts.append("✅ debtector: no architectural changes")
    for key, title, headers, build in sections:
        items = result[key]
        parts.append(f"\n### {title} ({len(items)})\n")
        parts.append(_row(headers))
        parts.append("|" + " --- |" * len(headers))
        parts.extend(_row(build(item)) for item in items[:MAX_ROWS])
        if len(items) > MAX_ROWS:
            parts.append(f"\n…and {len(items) - MAX_ROWS} more")
    for item in result.get("skipped", []):
        parts.append(f"\n> Skipped {_escape(item['section'])}: {_escape(item['reason'])}")
    return "\n".join(parts) + "\n"
