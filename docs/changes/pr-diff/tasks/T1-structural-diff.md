---
id: T1
title: debtector diff entre dos índices (estructura)
status: done
depends_on: []
examples: [E1, E2, E3, E4, E5, E6, E7]
verification: uv run pytest tests/test_diff.py -q
---

**Purpose:** comportamiento nuevo: `debtector diff <db_base> <db_pr>` lista los ciclos, god modules y violaciones SDP nuevos y resueltos, y las regresiones de inestabilidad, con las reglas de `baseline status` (D-0008).

**In:** el módulo `src/debtector/diff.py`, con la comparación y un resultado con una clave por sección. El subcomando `diff` en `cli.py`, con salida de texto y `--json`. Un `docs/diff-schema.md` con las secciones de esta tarea. Tests en `tests/test_diff.py`, con dos índices construidos en el test.

**Not in:** la validación de entradas y el código de salida por severidad (T2), `--base` (T3), la complejidad (T4), los hotspots (T5), el markdown (T6). `baseline status` no se toca.

**Flag:** ninguno.
