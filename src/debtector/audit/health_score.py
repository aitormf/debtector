"""Aggregated health score for the audit surface.

Reduces a heterogeneous list of audit findings (testRisk joins, future
coupling / cycle / cohesion findings) to a single ``0-100`` score plus a
breakdown by severity (``critical`` / ``high`` / ``medium`` / ``low``).

The score is a *deduction-from-100* metric: each finding subtracts a weight
according to its severity. The weights are tuned so a healthy project stays
above 80, a project with a handful of high-severity findings hovers around
50, and chronically debt-loaded projects floor at 0. Severities outside the
known buckets are ignored — callers can add new dimensions without forcing
a weight decision here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: Per-severity penalty applied to the score.
_SEVERITY_WEIGHTS: dict[str, int] = {
    "critical": 10,
    "high": 5,
    "medium": 2,
    "low": 1,
}


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
            the floor when penalties exceed 100 points.
        counts: Number of findings per severity bucket.
    """

    score: int
    counts: SeverityCounts

    # Prevent pytest from collecting this dataclass as a test class.
    __test__ = False


def compute_health_score(findings: Iterable[Any]) -> HealthScore:
    """Aggregate audit findings into a single health score.

    Args:
        findings: Iterable of objects exposing a ``severity`` attribute whose
            value is one of ``"critical"``, ``"high"``, ``"medium"``,
            ``"low"`` (case-insensitive). Unknown severities are ignored.

    Returns:
        A :class:`HealthScore` with the deducted score and per-severity counts.
    """
    counts: dict[str, int] = dict.fromkeys(_SEVERITY_WEIGHTS, 0)
    for finding in findings:
        severity = str(getattr(finding, "severity", "")).lower()
        if severity in counts:
            counts[severity] += 1

    penalty = sum(counts[sev] * weight for sev, weight in _SEVERITY_WEIGHTS.items())
    score = max(0, 100 - penalty)

    return HealthScore(score=score, counts=SeverityCounts(**counts))
