---
id: T3
title: Las anotaciones de tipo no cuentan en Ca ni Ce
status: todo
depends_on: [T2]
examples: [E10, E11, E12]
verification: uv run pytest -q tests/test_metrics_uses_type.py tests/test_metrics.py
---

**Purpose:** comportamiento nuevo: las aristas `USES_TYPE` dejan de sumar a Ca y a Ce (R3, D-0012).

**In:** `compute_metrics` en `src/debtector/metrics.py` deja de leer `USES_TYPE`; se retira `USES_TYPE_WEIGHT` y lo que solo lo usaba. `METRICS_VERSION` pasa a 3. `tests/test_metrics_uses_type.py` pasa a fijar que no cuentan. Docs de Ca/Ce si mencionan `USES_TYPE`.

**Not in:** la extracción de `USES_TYPE` en los parsers y su guardado en el índice siguen igual. Fachadas (T4).

**Flag:** ninguno.
