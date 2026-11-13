---
id: D-0017
title: "Las fachadas puras de paquete, Python o JS/TS, no participan en las violaciones SDP"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py, docs/audit-schema.md, docs/diff-schema.md]
supersedes: D-0013
superseded_by: null
issue: null
---

# D-0017: Las fachadas puras de paquete, Python o JS/TS, no participan en SDP

## Contexto

D-0013 sacó de SDP los `__init__.py` que solo reexportan. En JS/TS el mismo papel lo hacen los barrels `index.ts` (`export * from "./a.js"`). Cuando debtector empiece a extraer los reexports, darían el mismo ruido SDP.

## Decisión

Una fachada pura es un `__init__.py` o un `index.js`, `index.jsx`, `index.ts` o `index.tsx` sin nodos Class, Function ni Method en el índice. Las aristas que salen de una fachada pura o llegan a ella no se evalúan como violaciones SDP. Sus Ca y Ce se siguen calculando y mostrando. Un fichero índice con código propio es un módulo normal.

El resto de D-0013 sigue igual.

## Alternativas descartadas

- Reconocer como fachada cualquier fichero que solo reexporta, se llame como se llame: rara vez pasa fuera de los índices y obliga a analizar el contenido.
- Dejar los barrels en SDP: el ruido que D-0013 quitó en Python volvería en JS/TS.

## Cómo se hace cumplir

Los tests de R6 en `docs/changes/import-resolution/` y los de D-0013 en `tests/test_metrics_sdp.py`.
