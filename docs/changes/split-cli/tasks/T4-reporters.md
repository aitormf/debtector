---
id: T4
title: Reporters de CI en cli/reporters.py
status: done
depends_on: [T3]
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: mover las salidas de CI a `cli/reporters.py` (paso S4).

**In:** `_emit_github_annotations`, `_emit_gitlab_report`, `_annotation_level`, `_safe_annotation_path`, `_sdp_text`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** el comando `baseline` (T5). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
