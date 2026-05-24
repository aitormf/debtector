"""TestRisk joins: cross-cuts the graph allows but isolated reports don't.

Three pure-function joins over already-computed inputs:

- ``untested_high_coupling``: uncovered modules × high Ce — most dangerous to
  change blindly (callers everywhere, no tests to catch regressions).
- ``untested_hotspots``: uncovered modules × high churn — debt most likely
  to materialise into incidents.
- ``critical_knowledge_concentration``: bus factor 1 × high Ca — a single
  author owns a module many others depend on.

The joins operate on dataclasses produced by ``debtector.metrics`` and
``debtector.git_history`` so unit tests can build inputs directly without
touching git or the database. The audit command is the orchestrator that
wires them together end-to-end.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..git_history import BusFactorMetrics, ChurnMetrics
from ..metrics import ModuleMetrics

#: Default Ce above which an untested module is flagged "high-coupling".
DEFAULT_HIGH_CE: float = 10.0
#: Default commit count above which an untested module is flagged "hotspot".
DEFAULT_HIGH_CHURN: int = 5
#: Default Ca above which a bus-factor-1 module is "critical knowledge".
DEFAULT_HIGH_CA: float = 10.0


@dataclass(frozen=True)
class TestRiskFinding:
    """A module-level risk surfaced by a testRisk join.

    Args:
        file_path: Module that triggered the finding.
        label: Stable identifier of the join — ``"untested high-coupling"``,
            ``"untested hotspots"`` or ``"critical knowledge concentration"``.
        severity: ``"critical"`` for knowledge concentration, ``"high"`` for
            the untested joins. Consumed by the health-score aggregator.
        detail: Metric values that triggered the finding (e.g. ``fan_out``).
    """

    file_path: str
    label: str
    severity: str
    detail: dict[str, float] = field(default_factory=dict)

    # Prevent pytest from collecting this dataclass as a test class.
    __test__ = False


@dataclass(frozen=True)
class CohesionFinding:
    """A class-level low-cohesion finding.

    Args:
        qualified_name: Fully qualified name of the class.
        lcom4: LCOM4 value (1 = cohesive, >1 = candidate to split).
        methods_count: Number of methods in the class.
        candidate_to_split: Boolean flag if lcom4 > 1.
        severity: ``"high"`` for low-cohesion classes. Consumed by health-score.
    """

    qualified_name: str
    lcom4: float
    methods_count: int
    candidate_to_split: bool
    severity: str = "high"

    # Prevent pytest from collecting this dataclass as a test class.
    __test__ = False


def untested_high_coupling(
    untested_files: Iterable[str],
    module_metrics: Iterable[ModuleMetrics],
    ce_threshold: float = DEFAULT_HIGH_CE,
) -> list[TestRiskFinding]:
    """Flag uncovered modules whose Ce (fan-out) crosses ``ce_threshold``."""
    untested = set(untested_files)
    findings = [
        TestRiskFinding(
            file_path=m.file_path,
            label="untested high-coupling",
            severity="high",
            detail={"fan_out": m.fan_out},
        )
        for m in module_metrics
        if m.file_path in untested and m.fan_out >= ce_threshold
    ]
    findings.sort(key=lambda f: f.detail["fan_out"], reverse=True)
    return findings


def untested_hotspots(
    untested_files: Iterable[str],
    churn_metrics: Iterable[ChurnMetrics],
    churn_threshold: int = DEFAULT_HIGH_CHURN,
) -> list[TestRiskFinding]:
    """Flag uncovered modules whose commit count crosses ``churn_threshold``."""
    untested = set(untested_files)
    findings = [
        TestRiskFinding(
            file_path=c.file_path,
            label="untested hotspots",
            severity="high",
            detail={"commits": float(c.commits)},
        )
        for c in churn_metrics
        if c.file_path in untested and c.commits >= churn_threshold
    ]
    findings.sort(key=lambda f: f.detail["commits"], reverse=True)
    return findings


def critical_knowledge_concentration(
    bus_factor_metrics: Iterable[BusFactorMetrics],
    module_metrics: Iterable[ModuleMetrics],
    ca_threshold: float = DEFAULT_HIGH_CA,
) -> list[TestRiskFinding]:
    """Flag bus-factor-1 modules whose Ca crosses ``ca_threshold``."""
    ca_by_file: dict[str, float] = {m.file_path: m.fan_in for m in module_metrics}
    findings = [
        TestRiskFinding(
            file_path=b.file_path,
            label="critical knowledge concentration",
            severity="critical",
            detail={"fan_in": ca_by_file[b.file_path], "bus_factor": float(b.bus_factor)},
        )
        for b in bus_factor_metrics
        if b.bus_factor == 1 and ca_by_file.get(b.file_path, 0.0) >= ca_threshold
    ]
    findings.sort(key=lambda f: f.detail["fan_in"], reverse=True)
    return findings
