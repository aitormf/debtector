"""Architectural diff between two indexes (base vs. PR).

Uses the same rules as ``debtector baseline status`` (D-0008): cycles compared as
sets of modules, god modules by path, SDP violations by ``(source, target)`` and
instability regressions with a tolerance, ignoring modules that only exist in one side.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import MetricsSeverity, Severity
from .graph_store import GraphStore
from .metrics import (
    ModuleMetrics,
    compute_metrics,
    find_cycles,
    god_modules,
    sdp_violations,
)

_PARSER_VERSION_KEY = "parser_version"
_INDEX_TABLES = {"nodes", "edges", "metadata"}


class InvalidInputError(Exception):
    """The inputs of a diff cannot be compared (bad path, not an index, parser mismatch)."""


def validate_index(path: str) -> None:
    """Check that *path* is an existing debtector index, without creating or modifying it.

    Args:
        path: Path to the SQLite index.

    Raises:
        InvalidInputError: If the file does not exist or is not a debtector index.
    """
    if not Path(path).is_file():
        raise InvalidInputError(f"Index not found: {path}")
    try:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise InvalidInputError(f"Not a debtector index: {path}") from e
    if not _INDEX_TABLES <= tables:
        raise InvalidInputError(f"Not a debtector index: {path}")


def check_comparable(base: GraphStore, pr: GraphStore) -> None:
    """Refuse to compare indexes built by different parser versions (D-0008).

    Args:
        base: Index of the base branch.
        pr: Index of the PR.

    Raises:
        InvalidInputError: If their ``parser_version`` differs.
    """
    vb, vp = base.get_metadata(_PARSER_VERSION_KEY), pr.get_metadata(_PARSER_VERSION_KEY)
    if vb != vp:
        raise InvalidInputError(
            f"The indexes have a different parser_version (base: {vb}, PR: {vp}). "
            "Reindex both with the same debtector version: debtector index"
        )


def blocks_ci(result: dict, severity: MetricsSeverity) -> bool:
    """Whether something new in *result* has ``error`` severity (D-0008).

    Args:
        result: Output of :func:`compute_diff`.
        severity: The ``[metrics.severity]`` configuration.

    Returns:
        ``True`` if a new cycle, god module, SDP violation or instability regression
        belongs to a type configured as ``error``.
    """
    pairs = (
        ("new_cycles", severity.cycles),
        ("new_god_modules", severity.god_modules),
        ("new_sdp_violations", severity.instability),
        ("instability_regressions", severity.instability),
    )
    return any(result[key] and sev == Severity.ERROR for key, sev in pairs)


# A delta below 5% in instability is rounding noise, not real degradation.
INSTABILITY_TOLERANCE = 0.05
_FLOAT_EPSILON = 1e-9


def instability_grew(before: float, after: float) -> bool:
    """Whether instability grew more than :data:`INSTABILITY_TOLERANCE`.

    Uses an epsilon: ``0.40 - 0.35`` is ``0.05000000000000004`` in floating point, so a
    delta of exactly the tolerance does not count, while one visibly above it (0.05003) does.

    Args:
        before: Instability on the reference side (base or baseline).
        after: Current instability.

    Returns:
        ``True`` if the growth exceeds the tolerance.
    """
    return after - before > INSTABILITY_TOLERANCE + _FLOAT_EPSILON


def instability_regressions(base: list[ModuleMetrics], pr: list[ModuleMetrics]) -> list[dict]:
    """Modules present in both sides whose instability grew more than the tolerance.

    Args:
        base: Metrics of the base index.
        pr: Metrics of the PR index.

    Returns:
        One dict per regression with ``file_path``, ``metric``, ``before`` and ``after``.
    """
    before = {m.file_path: m.instability for m in base}
    return [
        {
            "file_path": m.file_path,
            "metric": "instability",
            "before": round(before[m.file_path], 4),
            "after": round(m.instability, 4),
        }
        for m in pr
        if m.file_path in before and instability_grew(before[m.file_path], m.instability)
    ]


def _cycle_diff(base: list[list[str]], pr: list[list[str]]) -> tuple[list, list]:
    base_sets = {frozenset(c) for c in base}
    pr_sets = {frozenset(c) for c in pr}
    return (
        [c for c in pr if frozenset(c) not in base_sets],
        [c for c in base if frozenset(c) not in pr_sets],
    )


def _sdp_dict(v) -> dict:
    return {
        "source": v.source,
        "target": v.target,
        "source_instability": round(v.source_instability, 3),
        "target_instability": round(v.target_instability, 3),
    }


def compute_diff(base: GraphStore, pr: GraphStore, cfg) -> dict[str, list]:
    """Compare the structure of two indexes.

    Args:
        base: Store of the base branch.
        pr: Store of the PR.
        cfg: Project config (thresholds of ``debtector.toml``).

    Returns:
        A dict with one key per section: ``new_cycles``, ``resolved_cycles``,
        ``new_god_modules``, ``resolved_god_modules``, ``new_sdp_violations``,
        ``resolved_sdp_violations`` and ``instability_regressions``.
    """
    thr = cfg.metrics.thresholds
    new_cycles, resolved_cycles = _cycle_diff(find_cycles(base), find_cycles(pr))

    def gods(store: GraphStore) -> list[str]:
        return [
            m.file_path
            for m in god_modules(
                store, percentile=thr.god_module_percentile, min_ca=thr.god_module_min_ca
            )
        ]

    base_gods, pr_gods = gods(base), gods(pr)

    def sdp(store: GraphStore) -> dict[tuple[str, str], dict]:
        return {
            (v.source, v.target): _sdp_dict(v) for v in sdp_violations(store, margin=thr.sdp_margin)
        }

    base_sdp, pr_sdp = sdp(base), sdp(pr)

    return {
        "new_cycles": new_cycles,
        "resolved_cycles": resolved_cycles,
        "new_god_modules": [p for p in pr_gods if p not in base_gods],
        "resolved_god_modules": [p for p in base_gods if p not in pr_gods],
        "new_sdp_violations": [v for k, v in pr_sdp.items() if k not in base_sdp],
        "resolved_sdp_violations": [v for k, v in base_sdp.items() if k not in pr_sdp],
        "instability_regressions": instability_regressions(
            compute_metrics(base), compute_metrics(pr)
        ),
    }
