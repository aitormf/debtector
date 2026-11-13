---
id: T4
title: Las fachadas puras no participan en SDP
status: todo
depends_on: [T3]
examples: [E13, E14, E15, E16]
verification: uv run pytest -q tests/test_metrics_sdp.py
---

**Purpose:** comportamiento nuevo: un `__init__.py` sin clases ni funciones no aparece en las violaciones SDP, ni como origen ni como destino (R4, D-0013).

**In:** `sdp_violations` en `src/debtector/metrics.py`, reconociendo las fachadas puras por sus nodos en el índice. `METRICS_VERSION` pasa a 4. Docs de SDP en `docs/audit-schema.md` y `docs/diff-schema.md`. Se vuelve a guardar `.debtector/baseline.json` del repo con `uv run debtector baseline save`. En `TODO.md` se marca hecha la entrada «SDP sin fachadas de paquete».

**Not in:** atravesar las fachadas para atribuir los imports a sus submódulos. Umbrales por defecto.

**Flag:** ninguno.
