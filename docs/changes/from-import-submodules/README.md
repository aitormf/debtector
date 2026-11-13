---
status: done
issue: null
---

# `from paquete import submódulo` depende del submódulo

**Problema:** en `from X import a, b` el parser guarda solo `X`, y la resolución manda la dependencia a `X/__init__.py` aunque `a` y `b` sean submódulos. El `__init__.py` acumula un Ca que no es suyo y sale como god module aunque esté vacío (`pydantic/_internal/__init__.py`, Ca 15; `src/blib2to3/pgen2/__init__.py` en black), y los submódulos de verdad (`_repr.py`, `driver.py`, `token.py`) pierden ese Ca: otro falso negativo. Además `from . import helper`, con `helper` una función del `__init__.py`, hoy no resuelve a nada. Lo vimos al medir los 13 repos públicos tras `import-resolution` (2026-11-13).

**Plazo máximo:** un día.

**Fuera de alcance:**
- Eximir los `__init__.py` de los god modules: un `__init__.py` con código debe contar por lo que se importa de él.
- JS/TS (`import { a } from "./dir"` con `dir/index.ts`): no tiene el problema, el import nombra el fichero.
- Seguir reexports para atribuir `from X import Clase` al fichero donde se define `Clase`.
- Cambiar la salida de `debtector imports`: la arista sigue teniendo como destino `X`.

## Mapa de ejemplos

```
Rule R1: el parser guarda los nombres importados en `from X import a, b`. → D-0018
  E1: `from blib2to3.pgen2 import grammar, token as t` → arista a `blib2to3.pgen2`
      con los nombres [grammar, token].
  E2: `from . import a, b as bee` → arista a `.` con los nombres [a, b] (hoy: aristas a `.a` y `.b`).
  E3: `from pkg import *` → arista a `pkg` sin nombres.
  E4: PARSER_VERSION sube en uno.

Rule R2: `from X import a` depende de `X/a.py` (o `X/a/__init__.py`) si `X.a` es un módulo del
         índice; si no, de `X` (su `__init__.py`), como ahora. → D-0018
  E5: src/blib2to3/pygram.py con `from .pgen2 import driver` → depende de
      src/blib2to3/pgen2/driver.py; Ca(pgen2/__init__.py) = 0.
  E6: `from pydantic._internal import _repr, _fields` → Ce = 2 (_repr.py y _fields.py);
      Ca(_internal/__init__.py) = 0.
  E7: `from app.models import User`, clase en app/models.py → depende de app/models.py (como hoy).
  E8: `from app import create_app`, función en app/__init__.py → depende de app/__init__.py.
  E9: `from app import models, create_app` → depende de app/models.py y de app/__init__.py; Ce = 2.
  E10: `from . import helper`, función en pkg/__init__.py → depende de pkg/__init__.py
       (hoy no resuelve).
  E11: `from pkg import sub` con pkg/sub/__init__.py → depende de pkg/sub/__init__.py.
  E12: `from pkg import *` → depende de pkg/__init__.py.
  E13: `from os import path` → ninguna dependencia interna.
  E14: METRICS_VERSION sube en uno.
```

## Supuestos

- Los nombres van en `extra` de la arista (`{"names": [...]}`), sin cambiar el schema: `extra` ya es JSON.
- La resolución por nombre se aplica igual en Ca/Ce, ciclos y SDP, que comparten `_resolve_import_target`.
- Un índice viejo sin `names` sigue resolviendo como hoy; el salto de `PARSER_VERSION` fuerza a reparsear.
- Al terminar se vuelven a medir black y pydantic: sus `__init__.py` vacíos dejan de ser god modules. Comprobación manual, no un test.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Cuáles están listas: el board de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
