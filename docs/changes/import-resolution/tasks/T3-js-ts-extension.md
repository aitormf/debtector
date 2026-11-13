---
id: T3
title: Un import .js/.jsx resuelve también al fichero .ts/.tsx
status: done
depends_on: []
examples: [E10, E11, E12, E13]
verification: uv run pytest tests/test_metrics_js_extensions.py -q
---
**Purpose:** que un import relativo JS/TS con extensión `.js`/`.jsx` resuelva al `.ts`/`.tsx` del mismo nombre cuando no existe el `.js`/`.jsx`, como TypeScript.
**In:** `_resolve_import_target` en `src/debtector/metrics.py` (prioridad al fichero exacto, luego `.js`→`.ts`, `.jsx`→`.tsx`), subir `METRICS_VERSION`, tests de E10 a E13 en `tests/test_metrics_js_extensions.py`.
**Not in:** alias de `tsconfig.json` (`paths`), cambios en el parser.
**Flag:** ninguno.
