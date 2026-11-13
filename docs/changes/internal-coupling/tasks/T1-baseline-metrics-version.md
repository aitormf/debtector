---
id: T1
title: El baseline guarda la versión de la métrica
status: todo
depends_on: []
examples: [E1, E2, E3, E4]
verification: uv run pytest -q tests/test_cli_baseline.py tests/test_ratcheting.py
---

**Purpose:** comportamiento nuevo: `baseline status` no compara el acoplamiento de un baseline guardado con otra versión de la métrica (R1, D-0014).

**In:** la constante `METRICS_VERSION = 1` en `src/debtector/metrics.py`. `baseline save` escribe `metrics_version` en `baseline.json`. `baseline status`: un baseline sin el campo es de la versión 1; con versión distinta avisa en el texto (y con un campo en `--json`), no compara inestabilidad, SDP ni god modules, y sigue comparando ciclos. Tests en `tests/test_cli_baseline.py` o `tests/test_ratcheting.py`, con baselines escritos en el test.

**Not in:** cambiar el cálculo de Ca/Ce (T2–T4). `debtector diff` no se toca.

**Flag:** ninguno.
