---
id: D-0018
title: "`from X import a` depende del submódulo `X.a` si existe; si no, de `X`"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py, src/debtector/parser/python_parser.py]
supersedes: null
superseded_by: null
issue: null
---

# D-0018: `from X import a` depende del submódulo `X.a` si existe; si no, de `X`

## Contexto

El parser guardaba solo `X` en `from X import a, b`, así que la dependencia iba siempre a `X/__init__.py`. Cuando `a` es un submódulo, el `__init__.py` recibía un Ca ajeno (salía como god module aunque estuviera vacío) y el submódulo lo perdía. Completa D-0016, que decide el nombre de cada módulo; esta decide a cuál apunta cada import.

## Decisión

- El parser guarda en la arista de `from X import ...` los nombres importados, en `extra.names`; la arista sigue apuntando a `X`. `from . import a` deja de dar una arista a `.a` y da una a `.` con el nombre `a`.
- Al resolver, cada nombre `a` que sea un módulo del índice (`X/a.py` o `X/a/__init__.py`) da una dependencia a ese fichero. Si queda algún nombre que no es módulo, o no hay nombres (`import *`), hay además una dependencia a `X`.
- Es la regla de Python: `from X import a` carga el submódulo `X.a` si existe; si no, toma el atributo `a` de `X`.

## Alternativas descartadas

- Eximir los `__init__.py` de los god modules: un `__init__.py` con código es un módulo como otro; el problema era la atribución, no el fichero.
- Que el parser emita directamente `X.a` como destino: el parser no sabe si `a` es un módulo, y las aristas a una clase quedarían sin resolver o se confundirían con imports externos.
- Seguir los reexports del `__init__.py` hasta el fichero que define cada nombre: más preciso, pero exige resolver símbolos y no solo módulos; no compensa ahora.

## Cómo se hace cumplir

Los tests de R1 y R2 en `docs/changes/from-import-submodules/`.
