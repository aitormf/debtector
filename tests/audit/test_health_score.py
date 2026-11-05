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
    result = compute_health_score([], modules=10)

    assert isinstance(result, HealthScore)
    assert result.score == 100
    assert result.counts == SeverityCounts(critical=0, high=0, medium=0, low=0)


def test_mixed_severities_report_exact_counts_and_score_below_100() -> None:
    """2 critical / 5 high / 10 medium / 20 low → counts surface verbatim, score <100."""
    result = compute_health_score(_findings(critical=2, high=5, medium=10, low=20), modules=100)

    assert result.counts.critical == 2
    assert result.counts.high == 5
    assert result.counts.medium == 10
    assert result.counts.low == 20
    assert result.score < 100
    assert 0 <= result.score <= 100


def test_unknown_severity_is_ignored() -> None:
    """Findings with an unrecognised severity do not affect score or counts."""
    result = compute_health_score([_Finding("informational"), _Finding("")], modules=10)

    assert result.score == 100
    assert result.counts == SeverityCounts()


def test_score_floors_at_zero_under_extreme_load() -> None:
    """Penalty greater than 100 is clamped: the score never goes negative."""
    result = compute_health_score(_findings(critical=50), modules=10)

    assert result.score == 0
    assert result.counts.critical == 50


def test_same_findings_score_better_in_a_bigger_project() -> None:
    """The penalty is normalised by module count: 3 high findings hurt 10 modules more."""
    small = compute_health_score(_findings(high=3), modules=10)
    large = compute_health_score(_findings(high=3), modules=100)

    assert small.score < large.score
    assert small.score == 70  # 100 - 100 * 15 / (5 * 10)
    assert large.score == 97  # 100 - 100 * 15 / (5 * 100) = 97


def test_zero_modules_scores_100() -> None:
    """No production modules → nothing to normalise by → perfect score, no ZeroDivisionError."""
    result = compute_health_score(_findings(critical=3), modules=0)

    assert result.score == 100


def test_one_high_finding_per_module_scores_zero() -> None:
    """On average one `high` finding per module is the floor."""
    assert compute_health_score(_findings(high=10), modules=10).score == 0


def test_score_is_rounded_to_int() -> None:
    """100 - 100 * 2 / (5 * 3) = 86.67 → 87, as an int."""
    result = compute_health_score(_findings(medium=1), modules=3)

    assert result.score == 87
    assert isinstance(result.score, int)
