"""Aggregated health score for the audit surface.

Reduces a heterogeneous list of audit findings (testRisk joins, actionable
hotspots) to a single ``0-100`` score plus a breakdown by severity
(``critical`` / ``high`` / ``medium`` / ``low``).

The score is a *deduction-from-100* metric normalised by project size: each
finding adds a weight according to its severity and the total is expressed
relative to ``5 * modules`` (one ``high`` finding per module on average →
``0``), so the same density of findings scores the same in a small and in a
large project. Severities outside the known buckets are ignored — callers can
add new dimensions without forcing a weight decision here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..metrics import percentile_threshold

#: Per-severity penalty applied to the score. Must match docs/audit-schema.md.
_SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 15,
    "high": 5,
    "medium": 2,
    "low": 0.5,
}

#: ``modules * _HIGH_WEIGHT`` is the total penalty that zeroes the score
#: (one ``high`` finding per module on average).
_HIGH_WEIGHT: float = _SEVERITY_WEIGHTS["high"]

#: Percentile of the project's ``hotspot_score`` a hotspot must reach to be scored.
DEFAULT_HOTSPOT_PERCENTILE: float = 90

#: Absolute ``hotspot_score`` (commits x (Ca + Ce)) a hotspot must reach to be
#: scored: e.g. 5 commits on a module with coupling 4, or 10 commits at coupling 2.
DEFAULT_HOTSPOT_MIN_SCORE: float = 20


@dataclass(frozen=True)
class SeverityCounts:
    """Count of findings grouped by severity bucket."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


@dataclass(frozen=True)
class HealthScore:
    """Aggregated audit score and its severity breakdown.

    Args:
        score: Integer in ``[0, 100]``. ``100`` means no issues, ``0`` is
            the floor when penalties reach one ``high`` finding per module.
        counts: Number of findings per severity bucket.
    """

    score: int
    counts: SeverityCounts

    # Prevent pytest from collecting this dataclass as a test class.
    __test__ = False


def select_actionable_hotspots(
    hotspots: Iterable[Any],
    percentile: float = DEFAULT_HOTSPOT_PERCENTILE,
    min_score: float = DEFAULT_HOTSPOT_MIN_SCORE,
) -> list[Any]:
    """Keep the hotspots worth scoring: top of the project *and* not trivial.

    A hotspot is actionable when its ``hotspot_score`` is at or above both the
    project's ``percentile`` of ``hotspot_score`` (relative cut, so only the
    worst of the project count) and ``min_score`` (absolute cut, so a project
    whose hotspots are all tiny scores none).

    Args:
        hotspots: Objects exposing ``hotspot_score``.
        percentile: Percentile in ``[1, 99]`` of the project's scores.
        min_score: Absolute minimum ``hotspot_score``.

    Returns:
        The actionable hotspots, in input order.
    """
    items = list(hotspots)
    if not items:
        return []
    cut = max(percentile_threshold([h.hotspot_score for h in items], percentile), min_score)
    return [h for h in items if h.hotspot_score >= cut]


def compute_health_score(findings: Iterable[Any], modules: int) -> HealthScore:
    """Aggregate audit findings into a single, size-normalised health score.

    ``score = max(0, 100 - 100 * sum(weight) / (5 * modules))``, rounded to int.

    Args:
        findings: Iterable of objects exposing a ``severity`` attribute whose
            value is one of ``"critical"``, ``"high"``, ``"medium"``,
            ``"low"`` (case-insensitive). Unknown severities are ignored.
        modules: Number of production modules. With ``0`` the score is ``100``.

    Returns:
        A :class:`HealthScore` with the normalised score and per-severity counts.
    """
    counts: dict[str, int] = dict.fromkeys(_SEVERITY_WEIGHTS, 0)
    for finding in findings:
        severity = str(getattr(finding, "severity", "")).lower()
        if severity in counts:
            counts[severity] += 1

    if modules <= 0:
        score = 100
    else:
        penalty = sum(counts[sev] * weight for sev, weight in _SEVERITY_WEIGHTS.items())
        score = max(0, round(100 - 100 * penalty / (_HIGH_WEIGHT * modules)))

    return HealthScore(score=score, counts=SeverityCounts(**counts))
