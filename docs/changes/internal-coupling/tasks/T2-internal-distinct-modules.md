---
id: T2
title: Ca y Ce cuentan módulos internos distintos
status: todo
depends_on: [T1]
examples: [E5, E6, E7, E8, E9]
verification: uv run pytest -q tests/test_metrics.py tests/test_metrics_resolution.py
---

**Purpose:** comportamiento nuevo: Ce y Ca cuentan solo los módulos internos distintos, sin imports externos ni duplicados (R2, D-0012).

**In:** `compute_metrics` en `src/debtector/metrics.py`: los imports que no se resuelven a un fichero del índice no suman a Ce; cada par (origen, destino) cuenta una vez. `METRICS_VERSION` pasa a 2. El docstring del módulo y la descripción de Ca/Ce en `docs/audit-schema.md` y `docs/diff-schema.md`. Los tests que hoy fijan el comportamiento viejo (p. ej. `test_fan_out_counts_external_imports`) se cambian por los ejemplos nuevos.

**Not in:** `USES_TYPE` (T3), fachadas (T4), umbrales por defecto.

**Flag:** ninguno.
