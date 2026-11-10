---
id: D-0004
title: "Complejidad ciclomática propia con tree-sitter, sin radon ni lizard"
type: architecture
status: accepted
date: 2026-11-10
affects: [src/debtector/parser/]
supersedes: null
superseded_by: null
issue: null
---

# D-0004: Complejidad ciclomática propia con tree-sitter, sin radon ni lizard

## Contexto

Para el hotspot de Tornhill hacía falta la complejidad de cada función. Radon ya la calcula, pero solo para Python, y debtector también indexa JS y TS. Lo que aporta debtector no es el número, sino cruzarlo con el churn, los tests, el bus factor y el ratcheting por PR.

## Decisión

Debtector calcula la complejidad ciclomática (McCabe) con tree-sitter, mientras recorre cada función al indexar, y la guarda en el `extra` del nodo (`complexity`, más `nested_complexity` para las funciones anidadas). En Python sigue las reglas de radon. Radon solo se usa como referencia en los tests. Cada parser nuevo trae sus propias reglas.

## Alternativas descartadas

- Radon como dependencia: solo cubre Python.
- Lizard como dependencia (cubre muchos lenguajes): hace un segundo parseo aparte de tree-sitter y obliga a emparejar sus funciones con nuestros `qualified_name` por número de línea, lo que es frágil con clases anidadas y lambdas.
- Complejidad cognitiva: más reglas y sin una referencia local con la que validarla.

## Cómo se hace cumplir

Los tests de `tests/parser/test_complexity.py` y `tests/parser/test_complexity_parsers.py` usan valores sacados de radon.
