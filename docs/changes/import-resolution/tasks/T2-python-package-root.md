---
id: T2
title: Los imports absolutos de Python se resuelven desde la raíz del paquete
status: done
depends_on: [T1]
examples: [E5, E6, E7, E8, E9]
verification: uv run pytest tests/test_metrics_package_root.py -q
---
**Purpose:** resolver los imports absolutos de Python por el nombre del módulo desde la raíz de su paquete (D-0016).
**In:** `_build_module_map` / `_resolve_import_target` en `src/debtector/metrics.py`: subir por los directorios con `__init__.py` del índice para dar el nombre del módulo, nombrar por su nombre los ficheros fuera de un paquete, no resolver los nombres ambiguos y seguir aceptando los nombres desde la raíz del repo; subir `METRICS_VERSION`; tests de E5 a E9 en `tests/test_metrics_package_root.py`.
**Not in:** leer `pyproject.toml`, namespace packages sin `__init__.py`, cualquier cambio en JS/TS.
**Flag:** ninguno. Depende de T1 para que los tests no sumen Ca al resolverse el layout `src/`.
