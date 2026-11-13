---
id: T2
title: `baseline save` guarda la complejidad de las funciones
status: todo
depends_on: []
examples: [E7, E8]
verification: uv run pytest tests/test_baseline_complexity.py -q
---

**Purpose:** que `baseline save` escriba `complexity: {medium, functions}` con las funciones de producción `>= complexity_medium` (D-0019).

**In:** `_baseline_save` en `src/debtector/cli/baseline.py`, reutilizando la selección de funciones de producción de `src/debtector/diff.py` (`_function_complexity`, o una función compartida si queda más claro), y los tests de E7 y E8 en `tests/test_baseline_complexity.py`.

**Not in:** compararla en `baseline status` (T3) y regenerar `.debtector/baseline.json` del repo (T3).

**Flag:** ninguno; `baseline status` ignora la clave nueva hasta T3.
