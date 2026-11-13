---
id: T2
title: Comandos del grafo en cli/graph.py
status: done
depends_on: [T1]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover los comandos de consulta del grafo a `cli/graph.py` (paso S2).

**In:** `cmd_index`, `cmd_search`, `cmd_summary`, `cmd_impact`, `cmd_imports`, `cmd_status`, `cmd_callers`; `__init__.py` los importa de `graph`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** los demás grupos. Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
