---
id: T5
title: Baseline en cli/baseline.py
status: done
depends_on: [T4]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover el comando `baseline` a `cli/baseline.py` (paso S5).

**In:** `cmd_baseline`, `_baseline_save`, `_baseline_status`, `_baseline_path`, `_BASELINE_FILE`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** los reporters (ya en T4). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
