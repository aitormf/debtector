---
id: T5
title: Un reexport export ... from crea un import
status: todo
depends_on: []
examples: [E18, E19, E20, E21]
verification: uv run pytest tests/parser/test_js_reexports.py -q
---
**Purpose:** extraer como IMPORTS_FROM los reexports `export * from`, `export { ... } from` y `export type { ... } from`.
**In:** la extracción de imports de `src/debtector/parser/js_parser.py` (los `export_statement` con `source`), subir `PARSER_VERSION` y `METRICS_VERSION`, tests de E18 a E21 en `tests/parser/test_js_reexports.py`.
**Not in:** tratar los barrels como fachadas en SDP (T6).
**Flag:** ninguno.
