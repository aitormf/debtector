---
id: T2
title: debtector.toml y .mailmap del propio repo
status: todo
depends_on: [T1]
examples: []
verification: uv run pytest -q
---

**Purpose:** preparación: que `debtector audit` sobre su propio repo vea los tests y un solo autor (paso S1).

**In:** `debtector.toml` en la raíz con `test_paths = ["tests"]`, y `.mailmap` que une `aitormf`, `aitor martinez` y `Aitor Martínez` en una identidad. Comprobación manual del paso S1, con el resultado en el cuerpo de la PR. `chore:`, sin release.

**Not in:** cambios de código; el baseline (`.debtector/baseline.json`) no cambia porque no depende de los tests ni de los autores.

**Flag:** ninguno.
