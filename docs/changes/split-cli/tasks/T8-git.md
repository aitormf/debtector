---
id: T8
title: Historial de git en cli/git.py
status: todo
depends_on: [T7]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover los comandos de historial de git a `cli/git.py` (paso S8).

**In:** `cmd_hotspots`, `cmd_temporal_coupling`, `cmd_bus_factor`, `cmd_git_coupling`. Sus `patch` en `tests/test_cli_git.py` pasan a `debtector.cli.git.*`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** los `patch` de las pruebas de `cmd_report` (T9). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
