---
id: D-0005
title: "El hotspot es churn × complejidad del fichero"
type: rule
status: accepted
date: 2026-11-10
affects: [src/debtector/git_history.py, src/debtector/audit/health_score.py, docs/audit-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0005: El hotspot es churn × complejidad del fichero

## Contexto

El hotspot era churn × acoplamiento (fan_in + fan_out). El acoplamiento mide cuánto se conecta un fichero, no lo difícil que es cambiarlo, así que el ranking metía ruido.

## Decisión

`hotspot_score = commits × complejidad del fichero`. La complejidad del fichero es la suma de `complexity + nested_complexity` de sus funciones y métodos. El acoplamiento se sigue mostrando, pero solo como dato informativo. Los ficheros sin funciones tienen score 0. El corte de accionables es p90 y `hotspot_min_score` = 50.

## Alternativas descartadas

- Churn × acoplamiento (la fórmula anterior): no mide la dificultad de cambiar el fichero.
- Añadir la complejidad solo como opción (`hotspots --by complexity`): `audit` seguiría usando la fórmula más ruidosa.

## Cómo se hace cumplir

Los tests de `tests/audit/test_hotspot_complexity.py` y `tests/test_git_history.py`. Lo que significa el score está versionado en `summary.health_score_version` (3).
