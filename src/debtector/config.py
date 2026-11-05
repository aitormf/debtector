"""
Configuración de Debtector desde ``debtector.toml``.

El archivo de configuración es opcional. Si no existe, se aplican los valores
por defecto. Los campos no especificados también usan sus valores por defecto.

Ejemplo de ``debtector.toml``:

.. code-block:: toml

    # Rutas de tests relativas a la raíz del proyecto (opcional). Se suman a
    # las convenciones por nombre y, si caen fuera del directorio indexado,
    # también se indexan para construir las aristas COVERS.
    test_paths = ["tests"]

    [metrics.thresholds]
    god_module_percentile = 90
    instability_threshold = 0.8
    max_inheritance_depth = 5
    max_children          = 10

    [metrics.severity]
    cycles      = "error"
    god_modules = "warning"
    instability = "warning"
    inheritance = "info"

    # Calibración de ``debtector audit`` (todo opcional; valores por defecto).
    [audit.thresholds]
    testrisk_high_ce    = 10   # Ce a partir del cual un módulo sin tests es "alto acoplamiento"
    testrisk_high_churn = 5    # commits a partir de los cuales un módulo sin tests es hotspot
    testrisk_high_ca    = 10   # Ca a partir del cual bus factor 1 es "conocimiento crítico"
    hotspot_percentile  = 90   # percentil de hotspot_score que debe alcanzar un hotspot
    hotspot_min_score   = 20   # hotspot_score mínimo absoluto (commits x (Ca + Ce))
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .audit.health_score import DEFAULT_HOTSPOT_MIN_SCORE, DEFAULT_HOTSPOT_PERCENTILE
from .audit.testrisk import DEFAULT_HIGH_CA, DEFAULT_HIGH_CE, DEFAULT_HIGH_CHURN


class Severity(StrEnum):
    """Nivel de severidad de una violación de métrica.

    - ``ERROR``   — termina con exit code 1; bloquea el CI.
    - ``WARNING`` — reporta la violación pero exit code 0; no bloquea.
    - ``INFO``    — solo informa, sin énfasis visual. Exit code 0.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class MetricsThresholds:
    """Umbrales numéricos para las métricas de acoplamiento.

    Args:
        god_module_percentile: Percentil de Ca por encima del cual un módulo
            se considera «god module». Default: 90.
        instability_threshold: Valor de I a partir del cual el módulo se
            considera inestable. Default: 0.8.
        max_inheritance_depth: Profundidad máxima de la jerarquía de herencia
            antes de generar un aviso. Default: 5.
        max_children: Número máximo de hijos directos en la jerarquía de
            herencia antes de generar un aviso. Default: 10.
    """

    god_module_percentile: float = 90
    instability_threshold: float = 0.8
    max_inheritance_depth: int = 5
    max_children: int = 10


@dataclass
class MetricsSeverity:
    """Severidad asociada a cada tipo de violación de métrica.

    Args:
        cycles: Ciclos de importación detectados.
        god_modules: Módulos con fan-in outlier.
        instability: Módulos con inestabilidad alta.
        inheritance: Jerarquías de herencia profundas o anchas.
    """

    cycles: Severity = Severity.ERROR
    god_modules: Severity = Severity.WARNING
    instability: Severity = Severity.WARNING
    inheritance: Severity = Severity.INFO


@dataclass
class MetricsConfig:
    """Configuración completa del subsistema de métricas."""

    thresholds: MetricsThresholds = field(default_factory=MetricsThresholds)
    severity: MetricsSeverity = field(default_factory=MetricsSeverity)


@dataclass
class AuditThresholds:
    """Umbrales de calibración de ``debtector audit`` (``[audit.thresholds]``).

    Args:
        testrisk_high_ce: Ce a partir del cual un módulo sin tests se marca
            como «alto acoplamiento». Default: 10.
        testrisk_high_churn: Commits a partir de los cuales un módulo sin
            tests se marca como hotspot. Default: 5.
        testrisk_high_ca: Ca a partir del cual un módulo con bus factor 1 es
            «conocimiento crítico». Default: 10.
        hotspot_percentile: Percentil (1-99) del ``hotspot_score`` del proyecto
            que debe alcanzar un hotspot para puntuar en el health score.
            Default: 90.
        hotspot_min_score: ``hotspot_score`` mínimo absoluto (commits x
            (Ca + Ce)) para puntuar en el health score. Default: 20.
    """

    testrisk_high_ce: float = DEFAULT_HIGH_CE
    testrisk_high_churn: int = DEFAULT_HIGH_CHURN
    testrisk_high_ca: float = DEFAULT_HIGH_CA
    hotspot_percentile: float = DEFAULT_HOTSPOT_PERCENTILE
    hotspot_min_score: float = DEFAULT_HOTSPOT_MIN_SCORE


@dataclass
class DebtectorConfig:
    """Configuración raíz de Debtector.

    Args:
        metrics: Configuración del subsistema de métricas.
        test_paths: Rutas (relativas a la raíz del proyecto, donde vive
            ``debtector.toml``) cuyos archivos son tests, además de las
            convenciones por nombre/directorio (``test_*``, ``tests/``...).
            Si apuntan fuera del directorio indexado, el indexador también
            las parsea para construir las aristas COVERS. Por defecto vacío:
            solo se usan las convenciones. Ejemplo: ``test_paths = ["tests"]``.
        audit: Umbrales de calibración de ``debtector audit``.
    """

    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    audit: AuditThresholds = field(default_factory=AuditThresholds)
    test_paths: list[str] = field(default_factory=list)


def load_config(project_root: str | Path) -> DebtectorConfig:
    """Carga la configuración desde ``debtector.toml`` en el directorio raíz.

    Si el archivo no existe, devuelve la configuración por defecto.
    Los campos no especificados en el toml mantienen sus valores por defecto.

    Args:
        project_root: Directorio raíz del proyecto donde buscar
            ``debtector.toml``.

    Returns:
        :class:`DebtectorConfig` con los valores del toml fusionados con
        los valores por defecto.

    Raises:
        ValueError: Si algún valor de severidad no es válido.
    """
    path = Path(project_root) / "debtector.toml"

    if not path.exists():
        return DebtectorConfig()

    with path.open("rb") as f:
        data = tomllib.load(f)

    metrics_data = data.get("metrics", {})

    # Thresholds — usamos una instancia default como fuente de verdad para
    # evitar acceder a atributos de clase de dataclass (frágil si se usara field())
    _thr_defaults = MetricsThresholds()
    thr_data = metrics_data.get("thresholds", {})
    thresholds = MetricsThresholds(
        god_module_percentile=thr_data.get(
            "god_module_percentile", _thr_defaults.god_module_percentile
        ),
        instability_threshold=thr_data.get(
            "instability_threshold", _thr_defaults.instability_threshold
        ),
        max_inheritance_depth=thr_data.get(
            "max_inheritance_depth", _thr_defaults.max_inheritance_depth
        ),
        max_children=thr_data.get("max_children", _thr_defaults.max_children),
    )

    # Severity — validamos explícitamente para dar error claro al usuario
    sev_data = metrics_data.get("severity", {})
    try:
        severity = MetricsSeverity(
            cycles=Severity(sev_data.get("cycles", MetricsSeverity.cycles.value)),
            god_modules=Severity(sev_data.get("god_modules", MetricsSeverity.god_modules.value)),
            instability=Severity(sev_data.get("instability", MetricsSeverity.instability.value)),
            inheritance=Severity(sev_data.get("inheritance", MetricsSeverity.inheritance.value)),
        )
    except ValueError as exc:
        valid = [s.value for s in Severity]
        raise ValueError(
            f"Valor de severidad inválido en debtector.toml. "
            f"Valores permitidos: {valid}. Detalle: {exc}"
        ) from exc

    test_paths = data.get("test_paths", [])
    if not isinstance(test_paths, list) or not all(isinstance(p, str) for p in test_paths):
        raise ValueError("`test_paths` en debtector.toml debe ser una lista de strings.")

    return DebtectorConfig(
        metrics=MetricsConfig(thresholds=thresholds, severity=severity),
        audit=_load_audit_thresholds(data.get("audit", {}).get("thresholds", {})),
        test_paths=list(test_paths),
    )


def _load_audit_thresholds(data: dict) -> AuditThresholds:
    """Valida y construye :class:`AuditThresholds` desde ``[audit.thresholds]``.

    Args:
        data: Tabla ``[audit.thresholds]`` ya parseada (vacía si no existe).

    Returns:
        Umbrales con los valores del toml fusionados con los por defecto.

    Raises:
        ValueError: Si un valor no es numérico, es negativo o el percentil
            queda fuera de ``[1, 99]``.
    """
    defaults = AuditThresholds()
    values: dict[str, float] = {}
    for key in AuditThresholds.__dataclass_fields__:
        value = data.get(key, getattr(defaults, key))
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(
                f"`audit.thresholds.{key}` en debtector.toml debe ser un número >= 0, "
                f"recibido {value!r}."
            )
        values[key] = value
    if not 1 <= values["hotspot_percentile"] <= 99:
        raise ValueError(
            "`audit.thresholds.hotspot_percentile` en debtector.toml debe estar en [1, 99], "
            f"recibido {values['hotspot_percentile']!r}."
        )
    return AuditThresholds(**values)
