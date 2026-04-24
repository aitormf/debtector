"""
Configuración de CodeIndex desde ``codeindex.toml``.

El archivo de configuración es opcional. Si no existe, se aplican los valores
por defecto. Los campos no especificados también usan sus valores por defecto.

Ejemplo de ``codeindex.toml``:

.. code-block:: toml

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
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


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
class CodeIndexConfig:
    """Configuración raíz de CodeIndex.

    Args:
        metrics: Configuración del subsistema de métricas.
    """

    metrics: MetricsConfig = field(default_factory=MetricsConfig)


def load_config(project_root: str | Path) -> CodeIndexConfig:
    """Carga la configuración desde ``codeindex.toml`` en el directorio raíz.

    Si el archivo no existe, devuelve la configuración por defecto.
    Los campos no especificados en el toml mantienen sus valores por defecto.

    Args:
        project_root: Directorio raíz del proyecto donde buscar
            ``codeindex.toml``.

    Returns:
        :class:`CodeIndexConfig` con los valores del toml fusionados con
        los valores por defecto.

    Raises:
        ValueError: Si algún valor de severidad no es válido.
    """
    path = Path(project_root) / "codeindex.toml"

    if not path.exists():
        return CodeIndexConfig()

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
            f"Valor de severidad inválido en codeindex.toml. "
            f"Valores permitidos: {valid}. Detalle: {exc}"
        ) from exc

    return CodeIndexConfig(metrics=MetricsConfig(thresholds=thresholds, severity=severity))
