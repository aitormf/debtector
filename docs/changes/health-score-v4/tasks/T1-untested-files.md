---
id: T1
title: Un fichero es "sin tests" solo si ningún símbolo tiene COVERS
status: done
depends_on: []
examples: [E1, E2, E3]
verification: uv run pytest tests/audit/test_untested_files.py -q
---

**Purpose:** corregir `_get_uncovered_files` (`src/debtector/cli.py`) para que devuelva los ficheros en los que ninguna función ni método tiene COVERS, como dice su docstring.

**In:** la consulta o el cálculo de ficheros sin tests (puede moverse a `GraphStore` o a `audit/testrisk.py` si queda más claro), y los tests de E1 a E3 en `tests/audit/test_untested_files.py`.

**Not in:** configurar `test_paths` en el propio repo (T2), y cualquier cambio de severidades o del health score.

**Flag:** ninguno.
