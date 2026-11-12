---
id: T5
title: Hotspots nuevos o que empeoran en el diff
status: done
depends_on: [T1]
examples: [E20, E21, E22]
verification: uv run pytest tests/test_diff_hotspots.py -q
---

**Purpose:** comportamiento nuevo: el diff incluye `new_hotspots` y `worsened_hotspots`, con el churn del repo de la PR en los dos lados y la complejidad de cada índice.

**In:** el cálculo de hotspots accionables y su severidad (`select_actionable_hotspots`, D-0007) para cada lado, y su comparación en `diff.py`. La sección `skipped` con el motivo en un clon superficial. Las secciones en el texto, el JSON y `docs/diff-schema.md`. Tests en `tests/test_diff_hotspots.py`.

**Not in:** que los hotspots bloqueen el CI. Cambiar la fórmula o el corte del hotspot.

**Flag:** ninguno.
