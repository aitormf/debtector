---
id: D-0010
title: "Qué funciones entran en el diff por complejidad"
type: rule
status: accepted
date: 2026-11-12
affects: [src/debtector/diff.py, docs/diff-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0010: Qué funciones entran en el diff por complejidad

## Contexto

Una PR toca muchas funciones y la mayoría cambia su complejidad en uno o dos puntos. Listarlas todas tapa lo que importa. Pero si solo se muestran las que cruzan un umbral, se pierde una función de 25 que sube a 35 dentro de la misma banda.

## Decisión

Una función de producción entra en `worsened_functions` si en la PR tiene complejidad ≥ `complexity_medium` y es nueva o su complejidad ha subido. Entra en `improved_functions` si estaba ≥ `complexity_medium` y en la PR baja de ese umbral o desaparece. La identidad es el `qualified_name`. Las funciones de tests no entran.

## Alternativas descartadas

- Listar cualquier cambio de complejidad: ruido.
- Solo las que cruzan un umbral: se escapan las que ya eran complejas y empeoran.
- Un delta mínimo (p. ej. +5): otro umbral que calibrar, sin datos para elegirlo.

## Cómo se hace cumplir

Los tests de `tests/test_diff_complexity.py` (T4 de `pr-diff`).
