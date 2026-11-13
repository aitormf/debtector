"""
Debtector configuration loaded from ``debtector.toml``.

The configuration file is optional. If it does not exist, the default values
are used. Fields that are not specified also use their default values.

Example of ``debtector.toml``:

.. code-block:: toml

    # Test paths relative to the project root (optional). They are added to
    # the name-based conventions and, if they fall outside the indexed
    # directory, they are also indexed to build the COVERS edges.
    test_paths = ["tests"]

    [metrics.thresholds]
    god_module_percentile = 90
    god_module_min_ca     = 10    # Minimum absolute Ca for a god module (besides the percentile)
    sdp_margin            = 0.1   # Minimum I(B) - I(A) to flag A -> B as an SDP violation
    # instability_threshold is deprecated: it is ignored (a warning is logged).
    max_inheritance_depth = 5
    max_children          = 10

    [metrics.severity]
    cycles      = "error"
    god_modules = "warning"
    instability = "warning"
    inheritance = "info"

    # Calibration of ``debtector audit`` (all optional; default values).
    [audit.thresholds]
    testrisk_high_ce    = 10   # Ce from which a module without tests is "high coupling"
    testrisk_high_churn = 5    # commits from which a module without tests is a hotspot
    testrisk_high_ca    = 10   # Ca from which bus factor 1 is "critical knowledge"
    hotspot_percentile  = 90   # hotspot_score percentile a hotspot must reach
    hotspot_min_score   = 50   # minimum absolute hotspot_score (commits x complexity)
    hotspot_high_factor = 3    # a hotspot is "high" from this multiple of the cut
    complexity_medium   = 21   # function complexity from which it is a "medium" finding
    complexity_high     = 31   # function complexity from which it is a "high" finding
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import structlog

from .audit.complexity import DEFAULT_COMPLEXITY_HIGH, DEFAULT_COMPLEXITY_MEDIUM
from .audit.defaults import DEFAULT_HIGH_CA, DEFAULT_HIGH_CE, DEFAULT_HIGH_CHURN
from .audit.health_score import (
    DEFAULT_HOTSPOT_HIGH_FACTOR,
    DEFAULT_HOTSPOT_MIN_SCORE,
    DEFAULT_HOTSPOT_PERCENTILE,
)

log = structlog.get_logger()


class Severity(StrEnum):
    """Severity level of a metric violation.

    - ``ERROR``   — exits with code 1; blocks CI.
    - ``WARNING`` — reports the violation but exits with code 0; does not block.
    - ``INFO``    — informational only, no visual emphasis. Exit code 0.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class MetricsThresholds:
    """Numeric thresholds for the coupling metrics.

    Args:
        god_module_percentile: Ca percentile above which a module
            is considered a "god module". Default: 90.
        god_module_min_ca: Minimum absolute Ca (inclusive) that a module must
            also reach to be a "god module". Prevents the percentile from
            always flagging something in small projects. Default: 10 (the same
            value as ``audit.thresholds.testrisk_high_ca``).
        sdp_margin: Minimum (strict) difference in I for a dependency
            ``A → B`` with ``I(B) > I(A)`` to count as a Stable
            Dependencies Principle violation. Default: 0.1.
        max_inheritance_depth: Maximum depth of the inheritance hierarchy
            before a warning is raised. Default: 5.
        max_children: Maximum number of direct children in the inheritance
            hierarchy before a warning is raised. Default: 10.
    """

    god_module_percentile: float = 90
    god_module_min_ca: float = DEFAULT_HIGH_CA
    sdp_margin: float = 0.1
    max_inheritance_depth: int = 5
    max_children: int = 10


@dataclass
class MetricsSeverity:
    """Severity associated with each type of metric violation.

    Args:
        cycles: Detected import cycles.
        god_modules: Modules with outlier fan-in.
        instability: Instability regressions and new SDP violations.
        inheritance: Deep or wide inheritance hierarchies.
        complexity: Functions that got worse in cyclomatic complexity (D-0019).
    """

    cycles: Severity = Severity.ERROR
    god_modules: Severity = Severity.WARNING
    instability: Severity = Severity.WARNING
    inheritance: Severity = Severity.INFO
    complexity: Severity = Severity.WARNING


@dataclass
class MetricsConfig:
    """Full configuration of the metrics subsystem."""

    thresholds: MetricsThresholds = field(default_factory=MetricsThresholds)
    severity: MetricsSeverity = field(default_factory=MetricsSeverity)


@dataclass
class AuditThresholds:
    """Calibration thresholds for ``debtector audit`` (``[audit.thresholds]``).

    Args:
        testrisk_high_ce: Ce from which a module without tests is flagged
            as "high coupling". Default: 10.
        testrisk_high_churn: Commits from which a module without
            tests is flagged as a hotspot. Default: 5.
        testrisk_high_ca: Ca from which a module with bus factor 1 is
            "critical knowledge". Default: 10.
        hotspot_percentile: Percentile (1-99) of the project's ``hotspot_score``
            that a hotspot must reach to count toward the health score.
            Default: 90.
        hotspot_min_score: Minimum absolute ``hotspot_score`` (commits x
            file cyclomatic complexity) to count toward the health score.
            Default: 50.
        hotspot_high_factor: Multiple of the actionable cut (``max(p90,
            hotspot_min_score)``) from which a hotspot is ``high`` instead of
            ``medium``; must be > 0. Default: 3.
        complexity_medium: Cyclomatic complexity from which a production
            function or method is a ``medium`` finding. Default: 21.
        complexity_high: Cyclomatic complexity from which it is a ``high``
            finding; must be >= ``complexity_medium``. Default: 31.
    """

    testrisk_high_ce: float = DEFAULT_HIGH_CE
    testrisk_high_churn: int = DEFAULT_HIGH_CHURN
    testrisk_high_ca: float = DEFAULT_HIGH_CA
    hotspot_percentile: float = DEFAULT_HOTSPOT_PERCENTILE
    hotspot_min_score: float = DEFAULT_HOTSPOT_MIN_SCORE
    hotspot_high_factor: float = DEFAULT_HOTSPOT_HIGH_FACTOR
    complexity_medium: float = DEFAULT_COMPLEXITY_MEDIUM
    complexity_high: float = DEFAULT_COMPLEXITY_HIGH


@dataclass
class DebtectorConfig:
    """Root Debtector configuration.

    Args:
        metrics: Metrics subsystem configuration.
        test_paths: Paths (relative to the project root, where
            ``debtector.toml`` lives) whose files are tests, in addition to the
            name/directory conventions (``test_*``, ``tests/``...).
            If they point outside the indexed directory, the indexer also
            parses them to build the COVERS edges. Empty by default:
            only the conventions are used. Example: ``test_paths = ["tests"]``.
        audit: Calibration thresholds for ``debtector audit``.
    """

    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    audit: AuditThresholds = field(default_factory=AuditThresholds)
    test_paths: list[str] = field(default_factory=list)


def load_config(project_root: str | Path) -> DebtectorConfig:
    """Load the configuration from ``debtector.toml`` in the root directory.

    If the file does not exist, return the default configuration.
    Fields not specified in the toml keep their default values.

    Args:
        project_root: Project root directory in which to look for
            ``debtector.toml``.

    Returns:
        :class:`DebtectorConfig` with the toml values merged with
        the defaults.

    Raises:
        ValueError: If a severity value is not valid.
    """
    path = Path(project_root) / "debtector.toml"

    if not path.exists():
        return DebtectorConfig()

    with path.open("rb") as f:
        data = tomllib.load(f)

    metrics_data = data.get("metrics", {})

    # Thresholds — use a default instance as the source of truth to
    # avoid accessing dataclass class attributes (fragile if field() were used)
    _thr_defaults = MetricsThresholds()
    thr_data = metrics_data.get("thresholds", {})
    if "instability_threshold" in thr_data:
        log.warning(
            "deprecated_config_key",
            key="metrics.thresholds.instability_threshold",
            reason="ignored: modules are flagged unstable only for SDP violations; see sdp_margin",
        )
    thresholds = MetricsThresholds(
        god_module_percentile=thr_data.get(
            "god_module_percentile", _thr_defaults.god_module_percentile
        ),
        god_module_min_ca=_non_negative(thr_data, "god_module_min_ca", _thr_defaults),
        sdp_margin=_non_negative(thr_data, "sdp_margin", _thr_defaults),
        max_inheritance_depth=thr_data.get(
            "max_inheritance_depth", _thr_defaults.max_inheritance_depth
        ),
        max_children=thr_data.get("max_children", _thr_defaults.max_children),
    )

    # Severity — validate explicitly to give the user a clear error
    sev_data = metrics_data.get("severity", {})
    try:
        severity = MetricsSeverity(
            cycles=Severity(sev_data.get("cycles", MetricsSeverity.cycles.value)),
            god_modules=Severity(sev_data.get("god_modules", MetricsSeverity.god_modules.value)),
            instability=Severity(sev_data.get("instability", MetricsSeverity.instability.value)),
            inheritance=Severity(sev_data.get("inheritance", MetricsSeverity.inheritance.value)),
            complexity=Severity(sev_data.get("complexity", MetricsSeverity.complexity.value)),
        )
    except ValueError as exc:
        valid = [s.value for s in Severity]
        raise ValueError(
            f"Invalid severity value in debtector.toml. Allowed values: {valid}. Detail: {exc}"
        ) from exc

    test_paths = data.get("test_paths", [])
    if not isinstance(test_paths, list) or not all(isinstance(p, str) for p in test_paths):
        raise ValueError("`test_paths` in debtector.toml must be a list of strings.")

    return DebtectorConfig(
        metrics=MetricsConfig(thresholds=thresholds, severity=severity),
        audit=_load_audit_thresholds(data.get("audit", {}).get("thresholds", {})),
        test_paths=list(test_paths),
    )


def _non_negative(data: dict, key: str, defaults: MetricsThresholds) -> float:
    """Read ``metrics.thresholds.<key>``, validating that it is a number >= 0.

    Args:
        data: Already parsed ``[metrics.thresholds]`` table.
        key: Name of the key.
        defaults: Instance holding the default values.

    Returns:
        The toml value or the default.

    Raises:
        ValueError: If the value is not numeric or is negative.
    """
    value = data.get(key, getattr(defaults, key))
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(
            f"`metrics.thresholds.{key}` in debtector.toml must be a number >= 0, got {value!r}."
        )
    return value


def _load_audit_thresholds(data: dict) -> AuditThresholds:
    """Validate and build :class:`AuditThresholds` from ``[audit.thresholds]``.

    Args:
        data: Already parsed ``[audit.thresholds]`` table (empty if absent).

    Returns:
        Thresholds with the toml values merged with the defaults.

    Raises:
        ValueError: If a value is not numeric, is negative, or the percentile
            falls outside ``[1, 99]``, ``hotspot_high_factor`` is 0, or
            ``complexity_medium`` > ``complexity_high``.
    """
    defaults = AuditThresholds()
    values: dict[str, float] = {}
    for key in AuditThresholds.__dataclass_fields__:
        value = data.get(key, getattr(defaults, key))
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(
                f"`audit.thresholds.{key}` in debtector.toml must be a number >= 0, got {value!r}."
            )
        values[key] = value
    if not 1 <= values["hotspot_percentile"] <= 99:
        raise ValueError(
            "`audit.thresholds.hotspot_percentile` in debtector.toml must be in [1, 99], "
            f"got {values['hotspot_percentile']!r}."
        )
    if values["hotspot_high_factor"] <= 0:
        raise ValueError(
            "`audit.thresholds.hotspot_high_factor` in debtector.toml must be > 0, "
            f"got {values['hotspot_high_factor']!r}."
        )
    if values["complexity_medium"] > values["complexity_high"]:
        raise ValueError(
            "`audit.thresholds.complexity_medium` in debtector.toml must be <= "
            f"`complexity_high`, got {values['complexity_medium']!r} > "
            f"{values['complexity_high']!r}."
        )
    return AuditThresholds(**values)
