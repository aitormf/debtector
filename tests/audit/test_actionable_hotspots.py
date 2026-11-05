"""Tests for the filter deciding which hotspots reach the health score.

Gherkin contract:

    Given los hotspots de un proyecto
    When se filtran para el score
    Then solo cuentan los que están en o por encima del percentil indicado del
         hotspot_score del proyecto Y en o por encima del mínimo absoluto
"""

from __future__ import annotations

from debtector.audit.health_score import (
    DEFAULT_HOTSPOT_MIN_SCORE,
    DEFAULT_HOTSPOT_PERCENTILE,
    select_actionable_hotspots,
)
from debtector.git_history import HotspotMetrics


def _hotspots(scores: list[float]) -> list[HotspotMetrics]:
    return [
        HotspotMetrics(file_path=f"m{i}.py", churn=1, coupling=s, hotspot_score=s)
        for i, s in enumerate(scores)
    ]


def test_defaults() -> None:
    """p90 and a minimum score of 50 (e.g. 5 commits on a module with complexity 10)."""
    assert DEFAULT_HOTSPOT_PERCENTILE == 90
    assert DEFAULT_HOTSPOT_MIN_SCORE == 50


def test_below_percentile_is_not_scored() -> None:
    """Only the outlier at/above p90 passes when everything else is below it."""
    hs = _hotspots([30.0] * 9 + [300.0])

    result = select_actionable_hotspots(hs, percentile=90, min_score=0)

    assert [h.hotspot_score for h in result] == [300.0]


def test_below_minimum_is_not_scored_even_above_percentile() -> None:
    """The top hotspot is above p90 but under the absolute minimum."""
    hs = _hotspots([1.0] * 9 + [10.0])

    assert select_actionable_hotspots(hs, percentile=90, min_score=20) == []


def test_above_both_is_scored() -> None:
    hs = _hotspots([1.0] * 9 + [50.0])

    result = select_actionable_hotspots(hs, percentile=90, min_score=20)

    assert [h.hotspot_score for h in result] == [50.0]


def test_all_tiny_hotspots_none_scored() -> None:
    hs = _hotspots([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])

    assert select_actionable_hotspots(hs) == []


def test_empty_and_single_hotspot() -> None:
    """No percentile can be computed from <2 points: only the minimum applies."""
    assert select_actionable_hotspots([]) == []
    assert select_actionable_hotspots(_hotspots([5.0])) == []
    assert len(select_actionable_hotspots(_hotspots([75.0]))) == 1


def test_percentile_is_configurable() -> None:
    """A lower percentile lets more hotspots through (still above the minimum)."""
    hs = _hotspots([30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0])

    strict = select_actionable_hotspots(hs, percentile=90, min_score=0)
    loose = select_actionable_hotspots(hs, percentile=50, min_score=0)

    assert len(loose) > len(strict) >= 1


def test_percentile_threshold_is_bounded_by_the_data() -> None:
    """Small samples must not extrapolate beyond [min, max]."""
    from debtector.metrics import percentile_threshold

    assert 20 <= percentile_threshold([20, 100], 90) <= 100
    assert 5 <= percentile_threshold([5, 5, 5, 100], 90) <= 100


def test_two_hotspots_score_the_top_one() -> None:
    result = select_actionable_hotspots(_hotspots([20.0, 100.0]), percentile=90, min_score=20)

    assert [h.hotspot_score for h in result] == [100.0]
