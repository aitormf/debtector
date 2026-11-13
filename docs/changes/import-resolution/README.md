---
status: done
issue: null
---

# Resolver los imports que hoy se pierden

**Problema:** en estructuras de proyecto muy comunes, debtector no ve los imports internos. Ca y Ce salen a 0, y el comentario de la PR y `baseline status` dicen que todo está limpio sin haberlo medido. Lo vimos indexando 13 repos públicos (2026-11-13):
- Python con layout `src/` e imports absolutos (black: `from blib2to3.pgen2.grammar import ...`, fichero `src/blib2to3/pgen2/grammar.py`). Es el layout estándar hoy, y el del propio debtector.
- TS con imports `.js` que apuntan a ficheros `.ts`, la convención ESM (got, zod).
- `require()` dentro de `var` o encadenado (`require('./utils').methods`); hoy solo se leen en `const`/`let` (express).
- Reexports `export * from "./x.js"` y `export { a } from "./b"`, que no se extraen (zod).

Además, los ficheros de test cuentan como módulos: salen como god modules (`tests/utils.py` en fastapi) y entran en el percentil. Arreglar el layout `src/` sin sacarlos antes haría que cada test que importa un módulo le sumara Ca.

**Plazo máximo:** tres días.

**Fuera de alcance:**
- Recalibrar los umbrales por defecto. Va después, con los mismos 13 repos y los números ya fiables.
- Alias de rutas de `tsconfig.json` (`paths`), workspaces y monorepos que importan su propio paquete por nombre (`import { z } from "zod"` dentro de zod).
- Namespace packages de Python sin `__init__.py` (PEP 420).
- `import()` dinámico y `require()` con argumento que no es un literal.
- Sacar de las métricas `scripts/`, `docs/` o benchmarks: para eso está `.codeindexignore`.

## Mapa de ejemplos

```
Rule R1: los ficheros de test no cuentan en las métricas de acoplamiento: ni como módulos
         ni como dependientes de un módulo. → D-0015
  E1: src/app/models.py importado por 3 módulos de producción y por 20 tests/test_*.py
      → Ca(models) = 3.
  E2: tests/utils.py importado por 15 tests → no aparece en las métricas ni como god module.
  E3: proyecto con 5 módulos de producción y 50 de test → el percentil de god modules se
      calcula sobre los 5.
  E4: METRICS_VERSION sube en uno.

Rule R2: un import absoluto de Python se resuelve por el nombre del módulo desde la raíz de
         su paquete (el primer directorio sin __init__.py), no desde la raíz del repo. → D-0016
  E5: src/blib2to3/__init__.py, src/blib2to3/pgen2/__init__.py y src/blib2to3/pgen2/grammar.py;
      src/blib2to3/pytree.py con `from blib2to3.pgen2.grammar import Grammar`
      → Ce(pytree) = 1, Ca(grammar) = 1.
  E6: src/blib2to3/x.py con `import blib2to3.pytree` → Ce(x) = 1.
  E7: layout plano: app/__init__.py, app/models.py, app/views.py con
      `from app.models import M` → Ce(views) = 1 (como hoy).
  E8: scripts/utils.py y tools/utils.py, sin __init__.py ninguno; a.py con `import utils`
      → nombre ambiguo, no se resuelve, Ce(a) = 0.
  E9: METRICS_VERSION sube en uno.

Rule R3: un import relativo JS/TS con extensión .js/.jsx resuelve también al fichero
         .ts/.tsx del mismo nombre, como hace TypeScript.
  E10: source/index.ts con `import { O } from "./core/options.js"`, fichero
       source/core/options.ts → Ce(index) = 1, Ca(options) = 1.
  E11: existen a/x.js y a/x.ts; `import "./x.js"` → resuelve a a/x.js.
  E12: `import C from "./c.jsx"`, fichero c.tsx → resuelve a c.tsx.
  E13: METRICS_VERSION sube en uno.

Rule R4: cualquier llamada `require("<literal>")` crea un import, esté donde esté.
  E14: `var View = require('./view')` → arista a ./view.
  E15: `var methods = require('./utils').methods` y `var debug = require('debug')('x')`
       → aristas a ./utils y a debug.
  E16: `require(name)` con una variable → ninguna arista.
  E17: PARSER_VERSION y METRICS_VERSION suben en uno.

Rule R5: un reexport `export ... from "<módulo>"` crea un import.
  E18: `export * from "./core.js"` → arista a ./core.js.
  E19: `export { a, b as c } from "./b"` y `export type { T } from "./t"` → aristas a ./b y ./t.
  E20: `export const x = 1` y `export { x }` sin `from` → ninguna arista.
  E21: PARSER_VERSION y METRICS_VERSION suben en uno.

Rule R6: un `index.js/.ts/.jsx/.tsx` sin clases ni funciones propias es una fachada pura,
         como un `__init__.py`, y no participa en SDP. → D-0017 (sustituye a D-0013)
  E22: lib/index.ts solo con `export * from "./a.js"` (I 0,9) y lib/a.ts (I 0,95)
       → no hay violación.
  E23: lib/index.ts que define `function create()` → sigue en SDP.
  E24: METRICS_VERSION sube en uno.
```

## Supuestos

- R1 usa la clasificación de tests que ya existe (`GraphStore.is_test_path`: convenciones de nombre, `tests/` y `test_paths`). No se inventa otra.
- R2 decide la raíz del paquete con los `__init__.py` del índice, sin leer `pyproject.toml`. Se siguen aceptando los nombres que hoy resuelven (la ruta entera con puntos), para no perder nada.
- Las tareas que cambian el parser (R4, R5) suben `PARSER_VERSION`: `diff` ya rechaza índices de versiones distintas (D-0008) y `index` vuelve a parsear.
- Cada tarea sube `METRICS_VERSION` (D-0014) porque sale en su propia release.
- Los tests de cada regla usan ficheros mínimos escritos en el test, no los repos públicos. Al terminar, se vuelven a indexar los 13 repos para comprobar que ya no salen a 0; es una comprobación manual, no un test.
- R6 va al final: con R5 aparecen las aristas de los barrels, y sin R6 darían el mismo ruido SDP que daban los `__init__.py`.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Cuáles están listas: el board de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
