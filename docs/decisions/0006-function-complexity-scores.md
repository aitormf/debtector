---
id: D-0006
title: "Las funciones con complejidad alta puntúan en el health score"
type: rule
status: accepted
date: 2026-11-10
affects: [src/debtector/cli.py, src/debtector/audit/, src/debtector/config.py, docs/audit-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0006: Las funciones con complejidad alta puntúan en el health score

## Contexto

Con la complejidad solo dentro del hotspot del fichero, una función con complejidad 40 no restaba nada por sí misma. El propio repo de debtector salía con 96/100 teniendo tres funciones por encima de 30.

## Decisión

Cada función o método de producción con complejidad ≥ `complexity_high` (31) es un hallazgo `high`. Con complejidad ≥ `complexity_medium` (21) y por debajo de 31 es `medium`. Los dos umbrales son configurables en `[audit.thresholds]`. Las funciones de los tests no cuentan. Una función compleja cuenta aunque su fichero ya sea hotspot, porque el hotspot mide el fichero y este hallazgo mide la función.

## Alternativas descartadas

- Que solo cuente a través del hotspot (lo que había): no distingue un fichero grande y simple de uno con una función imposible de leer.
- Puntuar la complejidad total del fichero: penaliza el tamaño, no la dificultad.
- Umbrales más bajos (11 y 21, las notas C y D de radon): marcaría como deuda código que es normal.

## Cómo se hace cumplir

Los tests de `tests/audit/test_complexity_findings.py` (T3 de `health-score-v4`). `summary.health_score_version` sube a 4.
