"""Architectural diff between two indexes (base vs. PR).

Uses the same rules as ``debtector baseline status`` (D-0008): cycles compared as
sets of modules, god modules by path, SDP violations by ``(source, target)`` and
instability regressions with a tolerance, ignoring modules that only exist in one side.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import structlog

from .audit.complexity import select_complexity_findings
from .audit.health_score import select_actionable_hotspots
from .config import MetricsSeverity, Severity
from .git_history import compute_hotspots, is_shallow_repository
from .graph_store import GraphStore
from .metrics import (
    ModuleMetrics,
    compute_metrics,
    find_cycles,
    god_modules,
    sdp_violations,
)
from .models import NodeKind

log = structlog.get_logger()

_PARSER_VERSION_KEY = "parser_version"
# Columns of the original schema that the diff reads (later migrations only add others).
_INDEX_COLUMNS = {
    "nodes": {"kind", "name", "qualified_name", "file_path", "extra"},
    "edges": {"kind", "source_qualified", "target_qualified", "file_path"},
    "metadata": {"key", "value"},
}


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
            columns = {
                table: {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                for table in _INDEX_COLUMNS
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise InvalidInputError(f"Not a debtector index: {path}") from e
    if any(not required <= columns[t] for t, required in _INDEX_COLUMNS.items()):
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


def _function_complexity(store: GraphStore) -> dict[str, tuple[int, str]]:
    """Complexity and file of every production function or method: id -> (complexity, path)."""
    nodes = store.get_nodes_by_kind(NodeKind.FUNCTION) + store.get_nodes_by_kind(NodeKind.METHOD)
    findings = select_complexity_findings(
        nodes, medium=0, high=float("inf"), is_test=store.is_test_path
    )
    return {f.qualified_name: (f.complexity, f.file_path) for f in findings}


def _complexity_diff(base: GraphStore, pr: GraphStore, thr) -> tuple[list[dict], list[dict]]:
    """Functions that got worse or better in complexity (D-0010).

    Args:
        base: Store of the base branch.
        pr: Store of the PR.
        thr: Audit thresholds (``complexity_medium`` / ``complexity_high``).

    Returns:
        ``(worsened, improved)``, each a list of ``{qualified_name, file_path, before,
        after, severity}`` with ``None`` for the side where the function does not exist.
    """
    before, after = _function_complexity(base), _function_complexity(pr)
    medium = thr.complexity_medium

    def severity(cx: int) -> str:
        return "high" if cx >= thr.complexity_high else "medium"

    worsened = [
        {
            "qualified_name": qn,
            "file_path": path,
            "before": before[qn][0] if qn in before else None,
            "after": cx,
            "severity": severity(cx),
        }
        for qn, (cx, path) in after.items()
        if cx >= medium and (qn not in before or cx > before[qn][0])
    ]
    improved = [
        {
            "qualified_name": qn,
            "file_path": path,
            "before": cx,
            "after": after[qn][0] if qn in after else None,
            "severity": severity(cx),
        }
        for qn, (cx, path) in before.items()
        if cx >= medium and (qn not in after or after[qn][0] < medium)
    ]
    return worsened, improved


def _hotspot_diff(
    base: GraphStore, pr: GraphStore, thr, project_root: str
) -> tuple[list[dict], list[dict]]:
    """Files that became actionable hotspots, or went from ``medium`` to ``high`` (D-0007).

    The churn is the one of the PR's repository on both sides, so only the complexity
    changes between them.

    Args:
        base: Store of the base branch.
        pr: Store of the PR.
        thr: Audit thresholds (``hotspot_*``).
        project_root: Git repository whose history gives the churn.

    Returns:
        ``(new, worsened)`` lists of dicts.
    """

    def actionable(store: GraphStore) -> dict[str, object]:
        found = select_actionable_hotspots(
            compute_hotspots(store, project_root),
            percentile=thr.hotspot_percentile,
            min_score=thr.hotspot_min_score,
            high_factor=thr.hotspot_high_factor,
        )
        return {h.file_path: h for h in found}

    before, after = actionable(base), actionable(pr)
    new, worsened = [], []
    for path, h in after.items():
        if path not in before:
            new.append(
                {
                    "file_path": path,
                    "churn": h.churn,
                    "complexity": h.complexity,
                    "hotspot_score": h.hotspot_score,
                    "severity": h.severity,
                }
            )
        elif before[path].severity == "medium" and h.severity == "high":
            worsened.append(
                {
                    "file_path": path,
                    "churn": h.churn,
                    "complexity_before": before[path].complexity,
                    "complexity_after": h.complexity,
                    "severity_before": "medium",
                    "severity": "high",
                }
            )
    return new, worsened


def compute_diff(
    base: GraphStore, pr: GraphStore, cfg, project_root: str | None = None
) -> dict[str, list | dict]:
    """Compare the structure of two indexes.

    Args:
        base: Store of the base branch.
        pr: Store of the PR.
        cfg: Project config (thresholds of ``debtector.toml``).
        project_root: Git repository of the PR, for the churn of the hotspots. Without it,
            or if it is not a repository, the hotspot sections are empty.

    Returns:
        A dict with one key per section: ``new_cycles``, ``resolved_cycles``,
        ``new_god_modules``, ``resolved_god_modules``, ``new_sdp_violations``,
        ``resolved_sdp_violations``, ``instability_regressions``, ``worsened_functions`` and
        ``improved_functions``, ``new_hotspots``, ``worsened_hotspots`` and ``skipped`` (a
        list of ``{section, reason}`` for what could not be computed, e.g. a shallow clone).
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

    worsened, improved = _complexity_diff(base, pr, cfg.audit)
    new_hotspots: list[dict] = []
    worsened_hotspots: list[dict] = []
    skipped: list[dict[str, str]] = []
    if project_root is not None:
        try:
            if is_shallow_repository(project_root):
                reason = (
                    "shallow clone: the history is truncated, so the churn is not reliable "
                    "(fetch with full depth, e.g. fetch-depth: 0)"
                )
                skipped.append({"section": "hotspots", "reason": reason})
            else:
                new_hotspots, worsened_hotspots = _hotspot_diff(base, pr, cfg.audit, project_root)
        except RuntimeError:
            # Not a git repository (or no git): no churn, so no hotspots.
            log.warning("diff_hotspots_unavailable", root=project_root, exc_info=True)

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
        "worsened_functions": worsened,
        "improved_functions": improved,
        "new_hotspots": new_hotspots,
        "worsened_hotspots": worsened_hotspots,
        "skipped": skipped,
    }
