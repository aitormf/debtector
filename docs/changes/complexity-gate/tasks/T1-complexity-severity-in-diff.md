---
id: T1
title: La severidad `complexity` decide si `diff` bloquea por complejidad
status: todo
depends_on: []
examples: [E1, E2, E3, E4, E5, E6]
verification: uv run pytest tests/test_complexity_severity.py -q
---

**Purpose:** que `[metrics.severity] complexity` (por defecto `warning`) haga que `diff` salga con 1 cuando hay funciones empeoradas y la severidad es `error` (D-0019).

**In:** el campo `complexity` en `MetricsSeverity` y su carga en `load_config` (`src/debtector/config.py`), `worsened_functions` en `blocks_ci` (`src/debtector/diff.py`), la frase "Complexity is informational: it never changes the exit code" de `docs/diff-schema.md` y la tabla de severidades de `README.md` / `README.es.md`, y los tests de E1 a E6 en `tests/test_complexity_severity.py`.

**Not in:** el baseline (T2, T3) y los hotspots, que siguen siendo informativos.

**Flag:** ninguno; el defecto `warning` mantiene el comportamiento actual.
