---
id: D-0009
title: "La GitHub Action vive en este repo y publica un comentario único"
type: architecture
status: accepted
date: 2026-11-12
affects: [action.yml, .github/workflows/, scripts/]
supersedes: null
superseded_by: null
issue: null
---

# D-0009: La GitHub Action vive en este repo y publica un comentario único

## Contexto

El TODO hablaba de un repo aparte, `debtector-action`. Una Action en otro repo tendría que versionarse a la vez que la CLI. Y si la PR recibe un comentario nuevo en cada push, se llena de ruido.

## Decisión

- La Action es compuesta (`action.yml` en la raíz de este repo) y se usa como `aitormf/debtector@vX`, con la misma versión que el paquete.
- Ejecuta `debtector diff --base <sha base> --format markdown`.
- Publica el resultado en un único comentario, que localiza por el marcador `<!-- debtector-diff -->` y actualiza en cada push.
- Lo escribe siempre en `$GITHUB_STEP_SUMMARY`.
- Si el token no puede comentar (PRs desde forks), lo avisa y no falla.
- Con `fail-on-error: true` (por defecto), el job falla después de publicar si `diff` sale con 1.

## Alternativas descartadas

- Un repo `debtector-action` aparte: dos versiones que mantener alineadas.
- Una Action JavaScript o Docker: más código y otra cadena de build para lo que es un comando de CLI.
- Un comentario nuevo por push: ruido en la PR.
- `pull_request_target` para comentar en forks: ejecuta código de la PR con un token de escritura.

## Cómo se hace cumplir

El workflow `.github/workflows/debtector.yml` usa la Action local en las PRs de este repo. El script que busca el comentario tiene tests (T7 de `pr-diff`).
