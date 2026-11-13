---
id: T3
title: Calidad en cli/quality.py
status: done
depends_on: [T2]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover los comandos de calidad a `cli/quality.py` (paso S3).

**In:** `cmd_complexity`, `cmd_untested`, `cmd_audit`, `_get_uncovered_files`, `_HEALTH_SCORE_VERSION`, `_complexity_findings`, `_single_author`. Los `patch` de `tests/test_cli_audit.py` pasan a `debtector.cli.quality.*`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** los demás grupos. Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
