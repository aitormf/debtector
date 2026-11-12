---
status: done
issue: null
---

# Health score v4: que el score refleje la deuda real

**Problema:** `debtector audit` da a su propio repo un 96/100, cuando tiene un fichero dios (`cli.py`, complejidad 292), una clase dios (`GraphStore`) y tres funciones con complejidad ciclomática por encima de 30. Hay tres causas:
1. **testRisk se salta.** El repo no configura `test_paths`. Si se configura, el score cae a 26 por un fallo: `_get_uncovered_files` marca como "sin tests" cualquier fichero en el que *un* símbolo no tenga COVERS (`graph_store.py` tiene 336).
2. **La complejidad de las funciones no puntúa.** Solo cuenta a través del hotspot del fichero.
3. **Todos los hotspots pesan lo mismo** (`medium`), aunque el de `cli.py` es 5 veces el siguiente.

A quien usa debtector como guardarraíl, un 96 le dice que no hay nada que mirar.

**Plazo máximo:** 1-2 días.

**Fuera de alcance:**
- Que la cohesión (LCOM4) puntúe: sigue siendo solo informativa.
- Llevar la complejidad al baseline o al ratcheting: llegará con `debtector diff`.
- Refactorizar `cli.py` o `GraphStore`: este cambio mide, no arregla lo medido.
- Cambiar los pesos por severidad (critical 15, high 5, medium 2).

## Mapa de ejemplos

Rule R1: un fichero de producción cuenta como "sin tests" solo si ninguna de sus funciones o métodos tiene una arista COVERS entrante.
  E1: fichero con 10 métodos, 9 cubiertos → no aparece en `untested_high_coupling` ni en `untested_hotspots`.
  E2: fichero con 3 funciones, ninguna cubierta y Ce ≥ `testrisk_high_ce` → aparece en `untested_high_coupling`.
  E3: fichero sin funciones ni métodos (solo constantes) → no aparece como "sin tests".
  Question: ¿bastaría con un umbral de cobertura por fichero (p. ej. < 50 % de símbolos cubiertos)? → No: "ninguno" coincide con el docstring actual y no inventa un umbral; el porcentaje se puede añadir más adelante. (Recomendado: ninguno).

Rule R2: cada función o método de producción con complejidad ≥ `complexity_high` (31 por defecto) es un hallazgo `high`. Con complejidad ≥ `complexity_medium` (21 por defecto) y por debajo de `complexity_high` es `medium`. Por debajo no hay hallazgo. → D-0006
  E4: función con complejidad 20 → sin hallazgo.
  E5: función con complejidad 21 → hallazgo `medium`.
  E6: función con complejidad 30 → `medium`; con 31 → `high`.
  E7: `[audit.thresholds] complexity_medium = 11` → una función con complejidad 11 es `medium`.
  E8: `complexity_medium = 40` y `complexity_high = 30` → error de configuración claro, como el resto de umbrales.
  E9: una función de un fichero de tests (bajo `test_paths` o por convención) con complejidad 50 → sin hallazgo.
  E10: `debtector --json audit` incluye una sección `complexity` con `qualified_name`, `complexity` y `severity` de cada hallazgo, y `summary.health_score_version` es 4.
  Question: una función compleja dentro de un fichero que ya es hotspot, ¿cuenta dos veces? → Sí: el hotspot mide cambio × complejidad del fichero y el hallazgo mide una función concreta difícil de cambiar. (Recomendado: sí).

Rule R3: un hotspot accionable es `medium`, y pasa a `high` si su `hotspot_score` es ≥ `hotspot_high_factor` (3 por defecto) × el corte de accionables (`max(p90, hotspot_min_score)`). → D-0007
  E11: corte 2574, hotspot de 12848 → `high`; el hotspot de 2574 → `medium`.
  E12: hotspot con score exactamente 3 × el corte → `high`.
  E13: un solo hotspot accionable, igual al corte → `medium`.
  E14: `debtector --json audit` devuelve la `severity` de cada hotspot y `summary.health_score_version` es 5.

Pasos (configuración del propio repo, no es una regla):
  S1: añadir `debtector.toml` con `test_paths = ["tests"]` y un `.mailmap` que una `aitormf`, `aitor martinez` y `Aitor Martínez` → verificar con `uv run debtector index ./src && uv run debtector --json audit`: `testRisk.status` es `ok`, `graph_store.py` y `cli.py` no salen como "sin tests", y `critical_knowledge_concentration` no puntúa (un solo autor).

## Supuestos

- Los umbrales 21 y 31 son las notas D y E de radon, la referencia más conocida para la ciclomática.
- Las funciones anidadas no tienen nodo propio, así que no generan hallazgos individuales. Su complejidad ya cuenta en el hotspot del fichero (#23).
- Cada tarea que cambia lo que significa el score sube `health_score_version`: 4 con R2 y 5 con R3. Cada una sale en su release.
- Los umbrales nuevos van en `[audit.thresholds]` y se validan igual que los existentes: numéricos, no negativos y `complexity_medium ≤ complexity_high`.
- `docs/audit-schema.md` y la sección de calibración del README (los dos idiomas) se actualizan en la misma tarea que cambia lo que documentan.
- Resultado esperado en este repo tras el cambio, solo como orientación y no como test: alrededor de 75. Saldría de 3 funciones `high`, 1 `medium`, `cli.py` como hotspot `high`, `graph_store.py` como `medium` y lo que de testRisk tras el fix.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Las que están listas se ven en el tablero de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
