---
id: T3
title: `baseline status` informa y bloquea las regresiones de complejidad
status: todo
depends_on: [T1, T2]
examples: [E9, E10, E11, E12, E13, E14, E15, E16]
verification: uv run pytest tests/test_baseline_status_complexity.py -q
---

**Purpose:** que `baseline status` compare la complejidad actual con la del baseline con la regla de D-0010 y bloquee según `[metrics.severity] complexity` (D-0019).

**In:** `_baseline_status` en `src/debtector/cli/baseline.py` (regresiones, salida humana, `--json` con `complexity_regressions`, avisos de baseline sin `complexity` o con `medium` mayor), los reporters de `src/debtector/cli/reporters.py` (GitHub y GitLab), regenerar `.debtector/baseline.json` del repo, la sección de ratcheting de los README, marcar el punto de complejidad en baseline en `TODO.md`, y los tests de E9 a E16 en `tests/test_baseline_status_complexity.py`.

**Not in:** listar las funciones que mejoran; hotspots.

**Flag:** ninguno.
