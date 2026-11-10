---
id: D-0007
title: "La severidad del hotspot depende de su magnitud respecto al corte"
type: rule
status: accepted
date: 2026-11-10
affects: [src/debtector/audit/health_score.py, src/debtector/git_history.py, src/debtector/config.py, docs/audit-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0007: La severidad del hotspot depende de su magnitud respecto al corte

## Contexto

Todos los hotspots accionables eran `medium`. En el propio repo, `cli.py` (12848) pesaba lo mismo que `graph_store.py` (2574), aunque su score es 5 veces mayor.

## Decisión

Un hotspot accionable es `medium`. Es `high` cuando `hotspot_score ≥ hotspot_high_factor × corte`, donde el corte es `max(p90, hotspot_min_score)` y `hotspot_high_factor` vale 3 por defecto, configurable en `[audit.thresholds]`.

## Alternativas descartadas

- Que todos sean `medium` (lo que había): un hotspot extremo pesa igual que uno justo en el corte.
- Un umbral absoluto de score: la escala depende del tamaño y de la edad del repo.
- Un segundo percentil (p. ej. p99): con pocos módulos coincide con el máximo, así que siempre marcaría uno.

## Cómo se hace cumplir

Los tests de `tests/audit/test_hotspot_severity.py` (T4 de `health-score-v4`). `summary.health_score_version` sube a 5.
