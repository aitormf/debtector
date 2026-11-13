---
id: T4
title: Cualquier require("<literal>") crea un import
status: todo
depends_on: []
examples: [E14, E15, E16, E17]
verification: uv run pytest tests/parser/test_js_require.py -q
---
**Purpose:** extraer como IMPORTS_FROM toda llamada `require()` con argumento literal, esté donde esté, no solo en `const`/`let`.
**In:** la extracción de imports de `src/debtector/parser/js_parser.py` (`_get_require_source` y su llamador: recorrer las `call_expression` a `require` con un string literal), subir `PARSER_VERSION` y `METRICS_VERSION`, tests de E14 a E17 en `tests/parser/test_js_require.py`.
**Not in:** `import()` dinámico, `require()` con argumento no literal, reexports (T5).
**Flag:** ninguno.
