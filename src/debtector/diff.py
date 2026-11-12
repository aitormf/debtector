"""Architectural diff between two indexes (base vs. PR).

Uses the same rules as ``debtector baseline status`` (D-0008): cycles compared as
sets of modules, god modules by path, SDP violations by ``(source, target)`` and
instability regressions with a tolerance, ignoring modules that only exist in one side.
"""

from __future__ import annotations

from .graph_store import GraphStore
from .metrics import (
    ModuleMetrics,
    compute_metrics,
    find_cycles,
    god_modules,
    sdp_violations,
)

# A delta below 5% in instability is rounding noise, not real degradation.
INSTABILITY_TOLERANCE = 0.05


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
        # Round the delta: 0.35 + 0.05 is 0.39999999999999997, a delta of exactly the
        # tolerance must not count as a regression.
        if m.file_path in before
        and round(m.instability - before[m.file_path], 4) > INSTABILITY_TOLERANCE
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
