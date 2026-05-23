"""Tests for the aggregated health score over audit findings.

Gherkin contract:

    Given un proyecto sin issues detectadas en ninguna dimensión
    When se calcula el health score
    Then el valor devuelto es 100 y todos los conteos por severidad son 0

    Given un proyecto con 2 critical, 5 high, 10 medium, 20 low
    When se calcula el health score
    Then los conteos exactos aparecen en el resultado y el score es <100
"""

from __future__ import annotations

from dataclasses import dataclass

from debtector.audit.health_score import HealthScore, SeverityCounts, compute_health_score


@dataclass(frozen=True)
class _Finding:
    """Minimal finding stub: only the severity attribute is consumed."""

    severity: str


def _findings(critical: int = 0, high: int = 0, medium: int = 0, low: int = 0) -> list[_Finding]:
    return (
        [_Finding("critical")] * critical
        + [_Finding("high")] * high
        + [_Finding("medium")] * medium
        + [_Finding("low")] * low
    )


def test_no_issues_returns_perfect_score() -> None:
    """No findings → score 100 and every severity count is 0."""
    result = compute_health_score([])

    assert isinstance(result, HealthScore)
    assert result.score == 100
    assert result.counts == SeverityCounts(critical=0, high=0, medium=0, low=0)


def test_mixed_severities_report_exact_counts_and_score_below_100() -> None:
    """2 critical / 5 high / 10 medium / 20 low → counts surface verbatim, score <100."""
    result = compute_health_score(_findings(critical=2, high=5, medium=10, low=20))

    assert result.counts.critical == 2
    assert result.counts.high == 5
    assert result.counts.medium == 10
    assert result.counts.low == 20
    assert result.score < 100
    assert 0 <= result.score <= 100


def test_unknown_severity_is_ignored() -> None:
    """Findings with an unrecognised severity do not affect score or counts."""
    result = compute_health_score([_Finding("informational"), _Finding("")])

    assert result.score == 100
    assert result.counts == SeverityCounts()


def test_score_floors_at_zero_under_extreme_load() -> None:
    """Penalty greater than 100 is clamped: the score never goes negative."""
    result = compute_health_score(_findings(critical=50))

    assert result.score == 0
    assert result.counts.critical == 50
