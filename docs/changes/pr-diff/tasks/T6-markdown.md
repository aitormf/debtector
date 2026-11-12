---
id: T6
title: Salida markdown del diff para comentarios de PR
status: done
depends_on: [T4, T5]
examples: [E23, E24, E25, E26]
verification: uv run pytest tests/test_diff_markdown.py -q
---

**Purpose:** comportamiento nuevo: `diff --format markdown` produce un comentario de PR con el marcador `<!-- debtector-diff -->`, todas las secciones, un máximo de 20 filas por sección y los textos escapados.

**In:** un renderizador de markdown (p. ej. `src/debtector/render/diff_markdown.py`) y la opción `--format markdown` en `cli.py`. Tests en `tests/test_diff_markdown.py`.

**Not in:** publicar el comentario (T7).

**Flag:** ninguno.
