---
id: T4
title: Funciones que empeoran o mejoran su complejidad en el diff
status: todo
depends_on: [T1]
examples: [E14, E15, E16, E17, E18, E19]
verification: uv run pytest tests/test_diff_complexity.py -q
---

**Purpose:** comportamiento nuevo: el diff incluye `worsened_functions` e `improved_functions` según D-0010.

**In:** la comparación por `qualified_name` de las funciones y métodos de producción, con el umbral `complexity_medium` y la severidad de `[audit.thresholds]` (reutilizando `audit/complexity.py`), en `diff.py`. Las dos secciones en el texto y el JSON de `diff` y en `docs/diff-schema.md`. Tests en `tests/test_diff_complexity.py`.

**Not in:** que la complejidad bloquee el CI (supuesto del README). Detectar renombrados.

**Flag:** ninguno.
