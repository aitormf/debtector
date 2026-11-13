---
id: T1
title: Los ficheros de test no cuentan en las métricas de acoplamiento
status: todo
depends_on: []
examples: [E1, E2, E3, E4]
verification: uv run pytest tests/test_metrics_test_files.py -q
---
**Purpose:** sacar los ficheros de test de las métricas de acoplamiento (D-0015): no son módulos ni cuentan como dependientes.
**In:** filtrar con `GraphStore.is_test_path` los ficheros y las aristas de import en `src/debtector/metrics.py` (Ca, Ce, ciclos, god modules y su percentil, SDP), subir `METRICS_VERSION`, actualizar `docs/audit-schema.md` y `docs/diff-schema.md` si describen qué módulos entran, y los tests de E1 a E4 en `tests/test_metrics_test_files.py`.
**Not in:** la resolución de nombres Python (T2) y cualquier cambio en la clasificación de tests (`is_test_path` se usa tal cual).
**Flag:** ninguno.
