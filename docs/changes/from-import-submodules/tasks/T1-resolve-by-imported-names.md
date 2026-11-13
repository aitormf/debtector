---
id: T1
title: La resolución usa los nombres importados para ir al submódulo
status: done
depends_on: []
examples: [E5, E6, E7, E8, E9, E10, E11, E12, E13]
verification: uv run pytest tests/test_metrics_from_import.py -q
---

**Purpose:** que la resolución de una arista `from X import ...` con `extra.names` dé una dependencia a cada nombre que sea un módulo del índice y otra a `X` si queda algún nombre que no lo es o no hay nombres (D-0018).

**In:** `src/debtector/metrics.py`: leer `extra` en las consultas de `IMPORTS_FROM` de Ca/Ce, ciclos y SDP, y una función que devuelva el conjunto de ficheros destino de una arista (reutilizando `_resolve_import_target` para `X` y para `X.a`). Los tests de E5 a E13 en `tests/test_metrics_from_import.py`, con aristas escritas a mano en el store (con `extra={"names": [...]}`), sin pasar por el parser.

**Not in:** el parser (T2) y las subidas de versión (T2): sin aristas con `names` no cambia ningún número.

**Flag:** ninguno. Una arista sin `names` resuelve como hoy, así que `main` no cambia hasta T2.
