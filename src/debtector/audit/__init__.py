"""Audit surface: second presenter over the existing graph backend.

See ``docs/decisions/003-audit-as-second-surface.md`` for the design rationale.
"""

from __future__ import annotations

from .cycle_priority import PrioritizedCycle, prioritize_cycles
from .health_score import HealthScore, SeverityCounts, compute_health_score
from .lcom4 import compute_lcom4
from .testrisk import (
    TestRiskFinding,
    critical_knowledge_concentration,
    untested_high_coupling,
    untested_hotspots,
)

__all__ = [
    "HealthScore",
    "PrioritizedCycle",
    "SeverityCounts",
    "TestRiskFinding",
    "compute_health_score",
    "compute_lcom4",
    "critical_knowledge_concentration",
    "prioritize_cycles",
    "untested_high_coupling",
    "untested_hotspots",
]
