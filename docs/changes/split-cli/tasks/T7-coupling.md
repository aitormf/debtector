---
id: T7
title: Acoplamiento en cli/coupling.py
status: todo
depends_on: [T6]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover el comando `coupling` a `cli/coupling.py` (paso S7).

**In:** `cmd_coupling` y su alias `cmd_metrics`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** `cmd_report` (T9). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
