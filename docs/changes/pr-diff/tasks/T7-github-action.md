---
id: T7
title: GitHub Action que comenta el diff en la PR
status: todo
depends_on: [T3, T6]
examples: [E27, E28, E29, E30]
verification: uv run pytest tests/test_action_publish.py -q
---

**Purpose:** comportamiento nuevo: la Action compuesta publica el diff de la PR en un único comentario y en el job summary, según D-0009.

**In:**
- `action.yml` en la raíz, con las entradas `fail-on-error` (true por defecto) y `version`: instala debtector con uv, indexa y ejecuta `debtector diff --base <sha base> --format markdown`.
- Un script de publicación en Python sin dependencias (`scripts/action_publish.py`) que busca el comentario por el marcador, lo crea o lo actualiza con la API REST, escribe `$GITHUB_STEP_SUMMARY`, avisa sin fallar si no puede comentar y devuelve el código de salida de `diff`.
- El workflow `.github/workflows/debtector.yml`, que usa `./` en las PRs de este repo.
- La documentación de uso en los dos READMEs y la fase 4 de `TODO.md`.
- Tests del script en `tests/test_action_publish.py`, con la API simulada. La PR de esta tarea debe mostrar el comentario publicado por el propio workflow.

**Not in:** el Marketplace, GitLab, SARIF. `pull_request_target`.

**Flag:** ninguno.
