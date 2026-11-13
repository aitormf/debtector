---
id: T6
title: Los index JS/TS sin clases ni funciones son fachadas puras
status: done
depends_on: [T5]
examples: [E22, E23, E24]
verification: uv run pytest tests/test_metrics_js_facades.py -q
---
**Purpose:** que un `index.js/.ts/.jsx/.tsx` sin clases ni funciones propias sea una fachada pura y no participe en SDP, como un `__init__.py` (D-0017, sustituye a D-0013).
**In:** `_pure_facades` en `src/debtector/metrics.py`, subir `METRICS_VERSION`, actualizar la descripción de fachadas en `docs/audit-schema.md` y `docs/diff-schema.md`, tests de E22 a E24 en `tests/test_metrics_js_facades.py`.
**Not in:** reconocer como fachada ficheros que no se llaman `index.*`.
**Flag:** ninguno. Depende de T5: sin las aristas de reexport no hay ruido que quitar.
