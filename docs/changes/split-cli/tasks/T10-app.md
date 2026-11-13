---
id: T10
title: Argparse en cli/app.py
status: done
depends_on: [T9]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover `main` a `cli/app.py`, dejando `cli/__init__.py` solo con `from .app import main` (paso S10).

**In:** `main` a `cli/app.py`; los `patch` de `tests/test_cli_human.py` pasan a `debtector.cli.app.*`; los tests que aún importen de `debtector.cli` algo distinto de `main` importan del submódulo. CLAUDE.md (árbol de arquitectura) y las filas *Affects* de `docs/decisions/README.md` y sus ficheros que dicen `src/debtector/cli.py` pasan a `src/debtector/cli/`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** cambiar el entry point de `pyproject.toml`. Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
