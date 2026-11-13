---
status: open
issue: null
---

# Ca y Ce miden solo el acoplamiento interno

**Problema:** las métricas de acoplamiento de debtector inflan la inestabilidad y generan alertas falsas en el comentario de la PR y en `baseline status`. Medido sobre el propio debtector (2026-11-13):
- Ce cuenta cada import, también de la librería estándar y de terceros. `graph_store.py` sale con Ce 21, pero solo depende de un módulo interno (`models`).
- Las aristas `USES_TYPE` suman a Ce una vez por cada anotación (`Path`, `NodeInfo`...), y a Ca nunca: su destino es un nombre de tipo, no un fichero, así que no se resuelve.
- Dos sentencias de import del mismo módulo cuentan dos veces.
- Un `__init__.py` que solo reexporta sus submódulos (`audit/__init__.py`) genera violaciones SDP hacia ellos.

Las tres violaciones SDP que salieron al partir la CLI (`cli/common.py → indexer.py`, `cli/common.py → graph_store.py`, `audit/__init__.py → audit/testrisk.py`) son de este tipo: contando solo dependencias internas desaparecen. Quien usa debtector en CI pierde confianza con cada falso positivo.

**Plazo máximo:** dos días.

**Fuera de alcance:**
- Recalibrar los umbrales por defecto (`god_module_min_ca`, `testrisk_high_ce`, `sdp_margin`). Necesita datos de varios repos; va en otro cambio.
- Agrupar Ca por paquete (ver D-0012, alternativas descartadas).
- Resolver los reexports de una fachada hasta el submódulo que define cada nombre.
- Cambiar la detección de ciclos o el uso de `CALLS`.
- Partir `GraphStore`.

## Mapa de ejemplos

```
Rule R1: baseline.json guarda la versión de la métrica de acoplamiento; `baseline status`
         no compara el acoplamiento de un baseline con otra versión. → D-0014
  E1: `debtector baseline save` → baseline.json incluye "metrics_version" con la versión actual.
  E2: baseline.json sin "metrics_version" y la versión actual es 1 → se compara como hoy
      (los baselines ya commiteados son de la versión 1).
  E3: baseline.json con "metrics_version": 1 y la versión actual es 2 → aviso
      "baseline saved with coupling metrics v1, current is v2: run debtector baseline save";
      no se comparan inestabilidad, SDP ni god modules; exit 0.
  E4: el mismo caso que E3 con un ciclo nuevo y `cycles = "error"` → el ciclo se compara
      y sale exit 1 (los ciclos no dependen de Ca/Ce).

Rule R2: Ce cuenta los módulos internos distintos que importa un módulo; Ca cuenta los
         módulos internos distintos que lo importan. Los imports externos no cuentan. → D-0012
  E5: a.py importa json, os, networkx y `from .b import X` → Ce(a) = 1, Ca(b) = 1.
  E6: a.py tiene `from .b import X` y `from .b import Y` en dos sentencias → Ce(a) = 1, Ca(b) = 1.
  E7: a.py solo importa json y pathlib, y nadie lo importa → Ca = 0, Ce = 0, I = 0.
  E8: a.js tiene `import React from "react"` e `import { x } from "./b"` → Ce(a) = 1.
  E9: tras el cambio, metrics_version pasa a 2.

Rule R3: las anotaciones de tipo (USES_TYPE) no suman a Ca ni a Ce: el import del tipo ya
         cuenta su módulo. → D-0012
  E10: a.py con `from .models import NodeInfo` y `def f(p: Path, n: NodeInfo) -> NodeInfo`
       → Ce(a) = 1, Ca(models) = 1.
  E11: a.py con anotaciones y sin imports internos → Ce(a) = 0.
  E12: tras el cambio, metrics_version pasa a 3.

Rule R4: un `__init__.py` que es una fachada pura (sin clases ni funciones propias) no
         participa en las violaciones SDP, ni como origen ni como destino. → D-0013
  E13: audit/__init__.py solo con `from .x import A` y `__all__` (I 0,8) → audit/x.py (I 0,9)
       → no hay violación.
  E14: c.py (I 0,2) → pkg/__init__.py fachada pura (I 0,9) → no hay violación.
  E15: parser/__init__.py define la clase ParserRegistry (no es fachada) → sigue en SDP:
       indexer.py (I 0,5) → parser/__init__.py (I 0,8) con margen 0,1 → violación.
  E16: tras el cambio, metrics_version pasa a 4.
```

## Supuestos

- La versión de la métrica es una constante entera en `metrics.py` (`METRICS_VERSION`), y cada tarea que cambia el cálculo la sube en uno. Cada tarea sale en su propia release, así que cada cambio de cálculo necesita su versión.
- `debtector diff` no necesita la versión: la Action indexa la base y la PR con el mismo debtector, y `diff` ya rechaza índices de distinto `parser_version` (D-0008).
- Las aristas `USES_TYPE` se siguen extrayendo y guardando; solo dejan de contar en Ca/Ce. Pueden servir para otras vistas.
- Una fachada pura se reconoce en el índice: un fichero `__init__.py` sin nodos Class ni Function. No hace falta mirar el contenido.
- El `.debtector/baseline.json` del propio repo (22 módulos) se vuelve a guardar en la última tarea que cambia la métrica. Ningún workflow de CI lo usa, así que entre tareas solo daría el aviso de versión.
- `docs/audit-schema.md`, `docs/diff-schema.md` y el docstring de `metrics.py` se actualizan en la tarea que cambia lo que describen.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Cuáles están listas: el board de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
