---
id: D-0015
title: "Los ficheros de test no cuentan en las métricas de acoplamiento"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py, docs/audit-schema.md, docs/diff-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0015: Los ficheros de test no cuentan en las métricas de acoplamiento

## Contexto

`compute_metrics` solo excluía los tests de fuera de la raíz (`../`, los de `test_paths`). Los de `tests/` dentro del repo eran módulos más: salían como god modules (`tests/utils.py` en fastapi), entraban en el percentil y, cuando sus imports se resuelven, sumaban Ca a cada módulo que prueban. Un módulo bien testeado parecía más acoplado.

## Decisión

Un fichero que `GraphStore.is_test_path` clasifica como test no aparece en Ca, Ce, inestabilidad, SDP ni god modules: ni como módulo ni como dependiente u objetivo de otro. Los tests siguen indexados y siguen dando las aristas `COVERS` y el audit de cobertura.

## Alternativas descartadas

- Contar los tests como dependientes con menos peso: el test depende del módulo por diseño; no es acoplamiento de arquitectura.
- Una lista propia de directorios a excluir: duplicaría la clasificación de tests que ya usan `COVERS` y `untested`, y podrían divergir.

## Cómo se hace cumplir

Los tests de R1 en `docs/changes/import-resolution/`.
