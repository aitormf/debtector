---
id: D-0014
title: "El baseline guarda la versión de la métrica y no se compara el acoplamiento entre versiones"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py, src/debtector/cli/baseline.py]
supersedes: null
superseded_by: null
issue: null
---

# D-0014: El baseline guarda la versión de la métrica

## Contexto

`baseline.json` se commitea y `baseline status` lo compara en CI con el índice actual. Si una release cambia cómo se calculan Ca y Ce, todos los módulos cambian de inestabilidad sin que el código cambie: el CI marcaría regresiones y violaciones falsas, o las escondería.

## Decisión

- `metrics.py` tiene `METRICS_VERSION`, un entero que sube cada vez que cambia el cálculo de Ca, Ce, inestabilidad, SDP o god modules.
- `baseline save` guarda `metrics_version` en `baseline.json`. Un baseline sin el campo es de la versión 1.
- Si la versión del baseline es distinta de la actual, `baseline status` avisa de que hay que volver a guardarlo y no compara inestabilidad, SDP ni god modules. Los ciclos se siguen comparando: no dependen de Ca/Ce. Ese aviso no hace fallar el CI.

## Alternativas descartadas

- Recalcular el baseline viejo con la métrica nueva: el baseline guarda métricas, no el índice, así que no se puede.
- Fallar con error hasta que se vuelva a guardar: rompe el CI de todos en la actualización, por un cambio que no es suyo.
- Comparar igualmente: falsos positivos o regresiones escondidas.

## Cómo se hace cumplir

Los tests de `tests/test_cli_baseline.py` y `tests/test_ratcheting.py` (tarea de R1 en `docs/changes/internal-coupling/`).
