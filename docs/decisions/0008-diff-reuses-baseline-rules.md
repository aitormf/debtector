---
id: D-0008
title: "debtector diff compara dos índices con las reglas de baseline status"
type: rule
status: accepted
date: 2026-11-12
affects: [src/debtector/diff.py, src/debtector/cli.py, docs/diff-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0008: debtector diff compara dos índices con las reglas de baseline status

## Contexto

`baseline status` compara el índice actual con un `baseline.json` commiteado. Una PR necesita compararse con su rama base real, sin depender de que alguien haya guardado el baseline. Si `diff` y `baseline status` usaran reglas distintas, la misma PR daría dos veredictos.

## Decisión

`debtector diff <db_base> <db_pr>` (o `--base <ref>`) compara dos índices de debtector:
- Ciclos: un ciclo es el mismo con independencia del orden.
- God modules y violaciones SDP: se calculan con la configuración del proyecto.
- Regresiones de inestabilidad: solo en módulos que existen en los dos lados y con la tolerancia de 0.05.

El código de salida sigue a `[metrics.severity]`: 1 si algo nuevo es `error`; 0 en otro caso; 2 si las entradas no son válidas, por ejemplo con distinto `parser_version`. Además de lo nuevo, lista lo resuelto.

## Alternativas descartadas

- Comparar contra el `baseline.json` de la rama base: depende de que esté al día, y no incluye la complejidad.
- Reglas propias para `diff`: dos veredictos distintos para la misma PR.
- Comparar índices con distinto `parser_version`: la complejidad cambiaría por la versión del parser, no por el código.

## Cómo se hace cumplir

Los tests de `tests/test_diff.py` (T1 y T2 de `pr-diff`).
