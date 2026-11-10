---
id: T4
title: Severidad del hotspot según su magnitud
status: done
depends_on: [T3]
examples: [E11, E12, E13, E14]
verification: uv run pytest tests/audit/test_hotspot_severity.py -q
---

**Purpose:** comportamiento nuevo: un hotspot accionable es `high` cuando su score es ≥ `hotspot_high_factor` × el corte de accionables, y `medium` en otro caso (D-0007).

**In:** `hotspot_high_factor` (3) en `[audit.thresholds]` con su validación, la asignación de severidad en `select_actionable_hotspots` o junto a ella, la `severity` de cada hotspot en el JSON y el texto de `audit`, `health_score_version` 5, `docs/audit-schema.md` y la sección de calibración de los dos READMEs. Tests en `tests/audit/test_hotspot_severity.py`.

**Not in:** la fórmula del hotspot (churn × complejidad, #23) y el corte de accionables (p90 y `hotspot_min_score`), que no cambian.

**Flag:** ninguno.
