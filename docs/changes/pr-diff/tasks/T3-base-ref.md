---
id: T3
title: diff --base <ref> con worktree temporal
status: todo
depends_on: [T2]
examples: [E11, E12, E13]
verification: uv run pytest tests/test_diff_base_ref.py -q
---

**Purpose:** comportamiento nuevo: `debtector diff --base <ref>` indexa la ref en un worktree temporal, la compara con el índice actual del proyecto y borra el worktree siempre.

**In:** el modo `--base` en `cli.py` (o un helper en `diff.py`), con `git worktree add --detach` en un directorio temporal, indexado con la misma ruta relativa que el índice actual (`index_root`), y `git worktree remove` en un `finally`. El error de uso cuando `--base` va con rutas de índice. Tests en `tests/test_diff_base_ref.py`, con un repo git creado en el test.

**Not in:** la Action (T7).

**Flag:** ninguno.
