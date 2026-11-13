---
id: D-0016
title: "Los imports absolutos de Python se resuelven desde la raíz del paquete"
type: architecture
status: accepted
date: 2026-11-13
affects: [src/debtector/metrics.py]
supersedes: null
superseded_by: null
issue: null
---

# D-0016: Los imports absolutos de Python se resuelven desde la raíz del paquete

## Contexto

El nombre de cada módulo se sacaba de su ruta desde la raíz del repo (`src/blib2to3/pgen2/grammar.py` → `src.blib2to3.pgen2.grammar`). En el layout `src/`, el estándar actual, el código importa `blib2to3.pgen2.grammar`, así que ningún import absoluto se resolvía y Ca/Ce salían a 0.

## Decisión

- El nombre de un módulo Python empieza en su paquete de más arriba: se sube por los directorios mientras tengan `__init__.py` en el índice. `src/blib2to3/pgen2/grammar.py` es `blib2to3.pgen2.grammar`.
- Un fichero fuera de cualquier paquete se nombra por su nombre (`scripts/utils.py` → `utils`).
- Si dos ficheros dan el mismo nombre, ese nombre no resuelve: mejor no contar una dependencia que atribuirla al módulo equivocado.
- Se siguen aceptando los nombres desde la raíz del repo que ya resolvían.

## Alternativas descartadas

- Leer las raíces de `pyproject.toml` (`[tool.setuptools] package-dir`, hatch, poetry...): cada herramienta lo declara distinto y muchos repos no lo declaran.
- Probar a quitar prefijos (`src.`, `lib.`) de una lista fija: falla con cualquier otro nombre de directorio.
- Configurarlo en `debtector.toml`: obliga a configurar algo que se puede deducir.

## Cómo se hace cumplir

Los tests de R2 en `docs/changes/import-resolution/`.
