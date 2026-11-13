---
id: T1
title: Paquete cli/ y helpers compartidos en cli/common.py
status: todo
depends_on: []
examples: []
verification: uv run pytest -q && uv run ruff check .
---

**Purpose:** refactor: convertir `cli.py` en el paquete `debtector/cli/` con los helpers compartidos en `cli/common.py` (paso S1).

**In:** `git mv src/debtector/cli.py src/debtector/cli/__init__.py` y mover a `cli/common.py`: `_INDEX_ROOT_KEY`, `_debtector_dir`, `_auto_index`, `_get_store`, `_open_store`, `_test_dirs`, `_test_prefixes`, `_index_root`, `_json_out`, `_configured_god_modules`, `_configured_sdp_violations`, `_sdp_dict`, `_blocks`, `_warns`, `_print_section`. `__init__.py` los importa de `common`, así que los `patch("debtector.cli._auto_index")` siguen valiendo mientras sus comandos sigan en `__init__`. Los tests que importan `_get_store` o `_debtector_dir` pasan a importarlos de `debtector.cli.common`. El código se mueve tal cual. En los tests solo cambian las rutas de import y de `patch(...)` de lo que se mueve (D-0011); ninguna aserción cambia.

**Not in:** mover comandos (T2–T9) y `main` (T10). Ningún cambio de comportamiento, salida ni argumentos; ningún renombrado de helpers.

**Flag:** ninguno.
