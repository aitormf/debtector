"""CI reporters: GitHub annotations and GitLab collapsible report."""

from __future__ import annotations

import time

from ..config import Severity
from .common import _warns


def _sdp_text(v: dict) -> str:
    """One-line description of an SDP violation dict (see :func:`_sdp_dict`)."""
    return (
        f"{v['source']} (I={v['source_instability']:.3f}) → "
        f"{v['target']} (I={v['target_instability']:.3f})"
    )


def _annotation_level(severity: Severity) -> str:
    """Map a :class:`Severity` to its GitHub Annotation level string."""
    return "error" if severity == Severity.ERROR else "warning"


def _safe_annotation_path(path: str) -> str:
    """Sanitize a file path for use in a GitHub Actions annotation.

    GitHub's ``::level file=<path>,...::`` format uses ``::`` as a delimiter.
    If a path contains ``::`` (e.g. a Debtector qualified_name), the annotation
    would be malformed.  Replace any occurrence with ``/`` to keep it readable.

    Args:
        path: Raw file path or qualified_name string.

    Returns:
        Path safe to embed inside a GitHub annotation parameter value.
    """
    return path.replace("::", "/")


def _emit_github_annotations(
    new_cycles: list,
    new_gods: list,
    regressions: list,
    sev,
    new_sdp: list | None = None,
) -> None:
    """Print GitHub Actions workflow commands for each regression.

    Format: ``::level file=<path>,line=1::<message>``

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
        new_sdp: List of new SDP violation dicts (see :func:`_sdp_dict`).
    """
    if _warns(new_cycles, sev.cycles):
        level = _annotation_level(sev.cycles)
        for cycle in new_cycles:
            safe_path = _safe_annotation_path(cycle[0])
            msg = f"Import cycle: {' → '.join(cycle)}"
            print(f"::{level} file={safe_path},line=1::{msg}")

    if _warns(new_gods, sev.god_modules):
        level = _annotation_level(sev.god_modules)
        for path_str in new_gods:
            safe_path = _safe_annotation_path(path_str)
            print(
                f"::{level} file={safe_path},line=1::"
                "God module: Ca exceeds the configured percentile"
            )

    if _warns(regressions, sev.instability):
        level = _annotation_level(sev.instability)
        for r in regressions:
            safe_path = _safe_annotation_path(r["file_path"])
            msg = f"Instability: {r['before']:.3f} → {r['after']:.3f}"
            print(f"::{level} file={safe_path},line=1::{msg}")

    new_sdp = new_sdp or []
    if _warns(new_sdp, sev.instability):
        level = _annotation_level(sev.instability)
        for v in new_sdp:
            safe_path = _safe_annotation_path(v["source"])
            print(f"::{level} file={safe_path},line=1::SDP violation: {_sdp_text(v)}")


def _emit_gitlab_report(
    new_cycles: list,
    new_gods: list,
    regressions: list,
    sev,
    new_sdp: list | None = None,
) -> None:
    """Print a GitLab CI–friendly report for each regression.

    Uses GitLab's ``section_start``/``section_end`` markers for collapsible
    log sections when issues are found.

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
        new_sdp: List of new SDP violation dicts (see :func:`_sdp_dict`).
    """
    ts = int(time.time())

    if _warns(new_cycles, sev.cycles):
        label = "ERROR" if sev.cycles == Severity.ERROR else "WARNING"
        print(f"\x1b[0Ksection_start:{ts}:cycles\r\x1b[0K[{label}] New cycles ({len(new_cycles)})")
        for cycle in new_cycles:
            print("  " + " → ".join(cycle) + " → ...")
        print(f"\x1b[0Ksection_end:{ts}:cycles\r\x1b[0K")

    if _warns(new_gods, sev.god_modules):
        label = "ERROR" if sev.god_modules == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:god_modules\r\x1b[0K"
            f"[{label}] New god modules ({len(new_gods)})"
        )
        for path_str in new_gods:
            print(f"  {path_str}")
        print(f"\x1b[0Ksection_end:{ts}:god_modules\r\x1b[0K")

    if _warns(regressions, sev.instability):
        label = "ERROR" if sev.instability == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:instability\r\x1b[0K"
            f"[{label}] Instability regressions ({len(regressions)})"
        )
        for r in regressions:
            print(f"  {r['file_path']}  I: {r['before']:.3f} → {r['after']:.3f}")
        print(f"\x1b[0Ksection_end:{ts}:instability\r\x1b[0K")

    new_sdp = new_sdp or []
    if _warns(new_sdp, sev.instability):
        label = "ERROR" if sev.instability == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:sdp\r\x1b[0K[{label}] New SDP violations ({len(new_sdp)})"
        )
        for v in new_sdp:
            print(f"  {_sdp_text(v)}")
        print(f"\x1b[0Ksection_end:{ts}:sdp\r\x1b[0K")
