---
id: T2
title: El parser guarda los nombres de `from X import a, b`
status: todo
depends_on: [T1]
examples: [E1, E2, E3, E4, E14]
verification: uv run pytest tests/parser/test_python_from_import_names.py -q
---

**Purpose:** que el parser de Python emita una sola arista por `from X import ...` hacia `X`, con los nombres importados en `extra.names` (D-0018).

**In:** `_extract_imports` / `_parse_from_modules` de `src/debtector/parser/python_parser.py` (también `from . import a, b`, que hoy da `.a` y `.b`), actualizar el test existente de `tests/parser/test_python_relative_imports.py` que espera `{".a", ".b"}`, subir `PARSER_VERSION` y `METRICS_VERSION`, regenerar `.debtector/baseline.json`, y los tests de E1 a E4 y E14 en `tests/parser/test_python_from_import_names.py`.

**Not in:** la resolución (T1), JS/TS.

**Flag:** ninguno.
