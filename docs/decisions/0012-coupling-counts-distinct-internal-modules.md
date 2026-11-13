---
id: D-0012
title: "Ca y Ce cuentan módulos internos distintos, sin imports externos ni anotaciones de tipo"
type: rule
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py, docs/audit-schema.md, docs/diff-schema.md]
supersedes: null
superseded_by: null
issue: null
---

# D-0012: Ca y Ce cuentan módulos internos distintos

## Contexto

Ce sumaba cada arista `IMPORTS_FROM` (también a `json`, `sqlite3`, `networkx`...) y cada arista `USES_TYPE` (una por anotación). Ca solo sumaba imports resueltos a ficheros del índice, y las `USES_TYPE` nunca se resolvían porque su destino es un nombre de tipo. El resultado: Ce inflado, inestabilidad alta en módulos estables (`graph_store.py`: Ce 21 con una sola dependencia interna) y violaciones SDP falsas en CI.

## Decisión

- **Ce(m)** = número de módulos internos distintos (ficheros del índice) que `m` importa.
- **Ca(m)** = número de módulos internos distintos que importan `m`.
- Los imports que no se resuelven a un fichero del índice (librería estándar, terceros) no cuentan.
- Varias sentencias de import del mismo módulo cuentan una vez.
- Las aristas `USES_TYPE` no cuentan: el tipo anotado ya se cuenta por el import que lo trae.

## Alternativas descartadas

- Contar los imports externos con menos peso: sigue mezclando dos cosas. La dependencia de librerías es otra métrica, no acoplamiento de arquitectura.
- Resolver `USES_TYPE` al módulo que define el tipo: aporta lo mismo que el import, con más código.
- Contar Ca por paquete (todos los módulos de `cli/` como un dependiente): partir un fichero dejaría de inflar Ca, pero en proyectos planos (todo en un directorio) Ca se queda en 0 o 1 y la métrica deja de servir. Martin define Ca por módulo.

## Cómo se hace cumplir

Los tests de `tests/test_metrics.py` y `tests/test_metrics_uses_type.py` (tareas de `docs/changes/internal-coupling/`).
