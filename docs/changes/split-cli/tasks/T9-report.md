---
id: T9
title: Informe combinado en cli/report.py
status: done
depends_on: [T8]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover el comando `report` a `cli/report.py` (paso S9).

**In:** `cmd_report`. Sus `patch` en `tests/test_cli_git.py` y `tests/test_cli_coupling_calibration.py` pasan a `debtector.cli.report.*`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** `main` (T10). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
