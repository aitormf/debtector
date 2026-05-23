"""Tests for the testRisk joins surfaced by the audit command.

Gherkin contract:

    Given un módulo untested con Ce=15 (alto)
    When se ejecuta el join 'untested high-coupling'
    Then el módulo aparece en la lista con etiqueta 'untested high-coupling'

    Given un módulo con bus_factor=1 y Ca=20
    When se ejecuta el join 'critical knowledge concentration'
    Then el módulo aparece marcado como riesgo crítico

    Given un módulo untested con churn alto
    When se ejecuta el join 'untested hotspots'
    Then aparece en la lista de hotspots de deuda probable
"""

from __future__ import annotations

from debtector.audit.testrisk import (
    TestRiskFinding,
    critical_knowledge_concentration,
    untested_high_coupling,
    untested_hotspots,
)
from debtector.git_history import BusFactorMetrics, ChurnMetrics
from debtector.metrics import ModuleMetrics


def _module(file_path: str, fan_in: float = 0.0, fan_out: float = 0.0) -> ModuleMetrics:
    total = fan_in + fan_out
    return ModuleMetrics(
        file_path=file_path,
        fan_in=fan_in,
        fan_out=fan_out,
        instability=(fan_out / total) if total else 0.0,
    )


class TestUntestedHighCoupling:
    """Cross of uncovered modules × high Ce (fan-out)."""

    def test_untested_module_with_high_ce_is_flagged(self) -> None:
        findings = untested_high_coupling(
            untested_files={"src/risky.py"},
            module_metrics=[_module("src/risky.py", fan_in=2, fan_out=15)],
        )

        assert len(findings) == 1
        assert isinstance(findings[0], TestRiskFinding)
        assert findings[0].file_path == "src/risky.py"
        assert findings[0].label == "untested high-coupling"

    def test_covered_module_is_not_flagged(self) -> None:
        findings = untested_high_coupling(
            untested_files=set(),
            module_metrics=[_module("src/safe.py", fan_out=20)],
        )
        assert findings == []

    def test_low_ce_untested_is_not_flagged(self) -> None:
        findings = untested_high_coupling(
            untested_files={"src/leaf.py"},
            module_metrics=[_module("src/leaf.py", fan_out=1)],
        )
        assert findings == []


class TestUntestedHotspots:
    """Cross of uncovered modules × high churn."""

    def test_untested_with_high_churn_is_flagged(self) -> None:
        findings = untested_hotspots(
            untested_files={"src/churny.py"},
            churn_metrics=[
                ChurnMetrics(file_path="src/churny.py", commits=30, lines_added=0, lines_deleted=0)
            ],
        )

        assert len(findings) == 1
        assert findings[0].label == "untested hotspots"
        assert findings[0].file_path == "src/churny.py"

    def test_covered_hotspot_is_not_flagged(self) -> None:
        findings = untested_hotspots(
            untested_files=set(),
            churn_metrics=[
                ChurnMetrics(file_path="src/x.py", commits=50, lines_added=0, lines_deleted=0)
            ],
        )
        assert findings == []


class TestCriticalKnowledgeConcentration:
    """Cross of bus_factor=1 × high Ca (fan-in)."""

    def test_bus_factor_one_with_high_ca_is_critical(self) -> None:
        findings = critical_knowledge_concentration(
            bus_factor_metrics=[
                BusFactorMetrics(
                    file_path="src/owned.py",
                    top_author="Ada",
                    top_author_pct=100.0,
                    bus_factor=1,
                )
            ],
            module_metrics=[_module("src/owned.py", fan_in=20)],
        )

        assert len(findings) == 1
        assert findings[0].label == "critical knowledge concentration"
        assert findings[0].severity == "critical"

    def test_high_ca_but_shared_ownership_is_not_critical(self) -> None:
        findings = critical_knowledge_concentration(
            bus_factor_metrics=[
                BusFactorMetrics(
                    file_path="src/shared.py",
                    top_author="Ada",
                    top_author_pct=40.0,
                    bus_factor=3,
                )
            ],
            module_metrics=[_module("src/shared.py", fan_in=20)],
        )
        assert findings == []
