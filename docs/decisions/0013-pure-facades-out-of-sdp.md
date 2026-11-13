---
id: D-0013
title: "Las fachadas puras de paquete no participan en las violaciones SDP"
type: rule
status: superseded
date: 2026-11-13
affects: [src/debtector/metrics.py, docs/audit-schema.md, docs/diff-schema.md]
supersedes: null
superseded_by: D-0017
issue: null
---

# D-0013: Las fachadas puras de paquete no participan en las violaciones SDP

## Contexto

Un `__init__.py` que solo reexporta sus submódulos depende de ellos por diseño y casi nadie lo importa directamente, así que su inestabilidad no dice nada. Aun así generaba violaciones SDP (`audit/__init__.py → audit/testrisk.py`).

## Decisión

Un `__init__.py` sin nodos Class ni Function en el índice es una fachada pura. Las aristas que salen de una fachada pura o llegan a ella no se evalúan como violaciones SDP. Sus Ca y Ce se siguen calculando y mostrando.

Un `__init__.py` con código propio (p. ej. `parser/__init__.py`, que define `ParserRegistry`) es un módulo normal y sigue en SDP.

## Alternativas descartadas

- Excluir solo las aristas de la fachada hacia su propio paquete: el caso inverso (un módulo estable que importa la fachada) también da violaciones sin sentido.
- Atravesar la fachada y atribuir cada import al submódulo que define el nombre: más preciso, pero necesita resolver reexports. Se puede hacer más adelante sin contradecir esta decisión.
- Excluir todos los `__init__.py`: esconde los que tienen lógica real.

## Cómo se hace cumplir

Los tests de `tests/test_metrics_sdp.py` (tarea de R4 en `docs/changes/internal-coupling/`).
