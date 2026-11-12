---
id: T2
title: Validación de entradas y código de salida de diff
status: todo
depends_on: [T1]
examples: [E8, E9, E10]
verification: uv run pytest tests/test_diff.py -q
---

**Purpose:** comportamiento nuevo: `diff` sale con 2 si las entradas no son válidas y con 1 si algo nuevo tiene severidad `error` en `[metrics.severity]` (D-0008).

**In:** la comprobación de que las dos rutas existen y son índices de debtector, la comparación de `parser_version` y el código de salida según las severidades, en `diff.py` y `cli.py`. Tests en `tests/test_diff.py`.

**Not in:** `--base` (T3). La complejidad y los hotspots no bloquean (supuesto del README).

**Flag:** ninguno.
