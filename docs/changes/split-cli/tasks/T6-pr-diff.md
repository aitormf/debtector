---
id: T6
title: Diff de PR en cli/pr_diff.py
status: done
depends_on: [T5]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover el comando `diff` a `cli/pr_diff.py` (paso S6).

**In:** `cmd_diff`, `_DIFF_SECTIONS`, `_diff_item`, `_git_out`, `_current_index_root`, `_refresh_index`, `_index_base_ref`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** `debtector.diff` no se toca. Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
