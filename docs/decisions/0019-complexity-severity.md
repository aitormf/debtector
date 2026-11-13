---
id: D-0019
title: "La complejidad tiene severidad propia y entra en el baseline"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/config.py, src/debtector/diff.py, src/debtector/cli/baseline.py, docs/diff-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0019: La complejidad tiene severidad propia y entra en el baseline

## Contexto

D-0010 decide qué funciones entran en el diff por complejidad, pero la sección era solo informativa: nunca cambiaba el código de salida, y el baseline no guardaba la complejidad. No había forma de bloquear una PR por una función nueva de complejidad 40, ni de verlo fuera de la GitHub Action.

## Decisión

- `[metrics.severity]` tiene una clave `complexity` (`error` | `warning` | `info`), por defecto `warning`. Se aplica a las funciones empeoradas según D-0010 (nuevas o que crecen, con complejidad `>= complexity_medium`). Con `error`, `diff` y `baseline status` salen con 1 si hay alguna; las mejoras nunca bloquean.
- `baseline save` guarda `complexity: {medium, functions: {qualified_name: complejidad}}` con las funciones de producción `>= complexity_medium`. `baseline status` compara con la misma regla de D-0010.
- Si el baseline no tiene `complexity`, o se guardó con un `complexity_medium` mayor que el actual, la complejidad no se compara y se avisa de volver a guardarlo.

## Alternativas descartadas

- Bloquear solo las funciones que llegan a `complexity_high`: otro umbral con el mismo efecto que subir `complexity_medium`; uno solo es más fácil de explicar.
- Guardar en el baseline todas las funciones: el fichero crece con cada función trivial y no cambia ningún resultado (ver Supuestos del cambio).
- Severidad por defecto `error`: cambiaría el código de salida de todos los usuarios al actualizar.
- Meter los hotspots en el baseline: dependen del churn, que cambia en cada commit.

## Cómo se hace cumplir

Los tests de R1, R2 y R3 en `docs/changes/complexity-gate/`.
