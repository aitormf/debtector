# ADR-002: Pivote — de navegación para IA a análisis de acoplamiento para CI/PR

**Estado:** Aceptado
**Fecha:** 2026-04-24
**Contexto:** CodeIndex v0.2

---

## Contexto

El objetivo original de codeIndex era que **una IA consultara el grafo en lugar de leer
archivos enteros**, reduciendo el consumo de tokens. El grafo (nodos + aristas IMPORTS_FROM,
CALLS, INHERITS, CONTAINS) se construyó para ese fin.

### Por qué ese objetivo falla

- El grafo tiene utilidad marginal para la IA: cuando Claude necesita *hacer algo*, igual
  necesita leer el código fuente para entender el contexto
- Las herramientas nativas de Claude Code (Glob, Grep, Read) ya resuelven el 90% de los
  casos de navegación sin infraestructura adicional
- El valor real requeriría proyectos de cientos de miles de líneas — la mayoría de los
  usuarios trabaja con codebases mucho más pequeños
- El MCP server era el único multiplicador real, pero no salva el producto por sí solo

### La oportunidad identificada

El grafo que ya existe es exactamente la estructura necesaria para computar **métricas de
acoplamiento**: Ca (fan-in), Ce (fan-out), inestabilidad, ciclos, god modules. No hay que
reescribir nada — solo añadir capas de análisis encima.

Existe un hueco real en el mercado: no hay herramienta open-source, ligera, multi-lenguaje
(Python + JS/TS) que combine análisis estructural + behavioral con CI integration sin
servidor. CodeScene lo resuelve pero es comercial. El resto son mono-lenguaje o están
estancados.

---

## Decisión

**Cambiar el usuario objetivo: ya no es la IA, es el desarrollador.**

El nuevo problema a resolver: **detectar acoplamiento de código en pipelines de CI y PR
reviews**, dando al desarrollador contexto arquitectónico antes de mergear.

### ICP (Ideal Customer Profile)

El ICP inicial es el **desarrollador o tech lead que usa agentes de código** (Claude Code,
Copilot, Codex). Es el perfil con el problema más agudo y sin solución actual:

- Los agentes generan código funcional que pasa tests, pero no tienen incentivo para
  respetar la arquitectura existente
- Un agente puede introducir en minutos el mismo nivel de deuda técnica que un equipo
  humano acumula en meses, de forma invisible
- codeIndex actúa como guardarraíl arquitectónico en el pipeline donde el agente genera código

### Roadmap resultante

**Fase 1 — Fundación estructural + gestión de ruido** (construible sobre el grafo existente)
Ca/Ce/inestabilidad, detección de ciclos, god modules, arista USES_TYPE, baseline +
ratcheting, severidad configurable, CI reporter.

**Fase 2 — Análisis behavioral** (git history)
Hotspots (churn × acoplamiento), temporal coupling, bus factor, integración Karajan.

**Fase 3 — Graph diff para PRs** (feature premium)
`codeindex diff <db_base> <db_pr>`, GitHub Action.

**Fase 4 — Features avanzadas**
Architectural layer violations, abstractness, tendencias históricas.

---

## Consecuencias

### Búsqueda semántica — congelada

`embedder.py`, `sqlite-vec` y `fastembed` no aportan valor al objetivo CI/PR. Para calcular
métricas de acoplamiento y diff de grafos, las consultas son SQL puro sobre el grafo;
nunca se necesita búsqueda por concepto semántico.

Decisión: **congelar, no eliminar**.

- `fastembed` y `sqlite-vec` movidos a grupo opcional `[semantic]` en `pyproject.toml`
- `codeindex semantic` devuelve error con mensaje de deprecación
- El código se conserva; se eliminará cuando el roadmap de CI esté avanzado
- Motivo de no eliminar de golpe: hay código funcional y 23 tests — el riesgo de
  romper algo en el refactor no compensa la ganancia inmediata

### Gestión de ruido — condición de supervivencia

SonarQube se desinstala porque la primera ejecución sobre un codebase real genera cientos
de warnings sobre deuda existente. codeIndex tiene el mismo riesgo.

Solución obligatoria desde el día uno:

- **Baseline**: snapshot del estado actual → deuda existente no bloquea CI
- **Ratcheting**: el CI solo falla si las métricas *empeoran* respecto al baseline
- **Severidad configurable**: `error` / `warning` / `info` por tipo de problema
- **Modo silencioso por defecto**: sin baseline configurado, solo reporta, no falla

### Persistencia del baseline

`.codeindex/baseline.json` commiteado al repo (no en `index.db`):
- Compartido entre todos los miembros del equipo y el CI sin infraestructura adicional
- Human-readable y diffable en git
- El `.codeindex/.gitignore` se gestiona automáticamente: siempre sobreescrito por
  codeIndex, trackea `baseline.json`, ignora `*.db` y `*.log`

### Qué no cambia

- El grafo SQLite (nodos + aristas) es la base — no se toca
- Los parsers (Python, JS/TS) no cambian
- El CLI existente (`index`, `search`, `impact`, `callers`, `untested`) no cambia
- FTS5 se mantiene — tiene valor marginal para navegación humana

---

## Alternativas descartadas

**Eliminar la búsqueda semántica de golpe**
Descartado: hay código funcional y tests. El riesgo de rotura no compensa.

**Mantener el objetivo de IA como usuario secundario**
Descartado: diluye el foco y complica el posicionamiento. El ICP debe ser uno.

**Implementar graph diff antes que el baseline**
Descartado: graph diff es el feature más diferencial técnicamente, pero necesita más
contexto para venderse. Sin baseline + ratcheting la herramienta muere en la primera
demo. El orden importa.
