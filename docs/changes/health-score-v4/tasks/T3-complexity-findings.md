---
id: T3
title: La complejidad de cada función puntúa en el health score
status: todo
depends_on: []
examples: [E4, E5, E6, E7, E8, E9, E10]
verification: uv run pytest tests/audit/test_complexity_findings.py -q
---

**Purpose:** comportamiento nuevo: las funciones y métodos de producción con complejidad ≥ `complexity_medium` o ≥ `complexity_high` son hallazgos `medium` o `high` del health score (D-0006).

**In:** los umbrales `complexity_medium` (21) y `complexity_high` (31) en `[audit.thresholds]` con su validación, los hallazgos de complejidad en `cmd_audit`, la sección `complexity` del JSON de `audit` y su salida de texto, `health_score_version` 4, `docs/audit-schema.md` y la sección de calibración de los dos READMEs. Tests en `tests/audit/test_complexity_findings.py`.

**Not in:** la severidad de los hotspots (T4), el baseline y el ratcheting, y los pesos por severidad.

**Flag:** ninguno.
