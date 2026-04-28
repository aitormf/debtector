# TODO — Debtector

Roadmap orientado a análisis de acoplamiento para CI/PR.
ICP: dev/tech lead que usa agentes de código.

---

## Fase 1 — Fundación estructural + gestión de ruido
*Construible sobre el grafo existente. Sin esto no hay producto.*

- [x] **`metrics.py`** — módulo de métricas de acoplamiento:
  - Fan-in (Ca): aristas IMPORTS_FROM entrantes al módulo
  - Fan-out (Ce): aristas IMPORTS_FROM salientes del módulo
  - Inestabilidad (I): Ce / (Ca + Ce) — 0 estable, 1 inestable
- [x] **Detección de ciclos** — DFS sobre aristas IMPORTS_FROM + CALLS
- [x] **God module detection** — outliers estadísticos en Ca (percentil 90 del proyecto, no umbral absoluto)
- [x] **Profundidad de herencia y número de hijos** — traverse INHERITS edges
- [x] **Arista `USES_TYPE`** — `def f(x: User) -> Response` genera aristas hacia `User` y `Response`; enriquece Ca/Ce sin nueva fuente de datos
- [x] **Comando `debtector coupling`** — output tabular con Ca, Ce, I, ciclos, god modules por módulo (antes `metrics`, alias conservado)
- [x] **Baseline** — `debtector baseline save` guarda snapshot de métricas en `.debtector/baseline.json`; `debtector baseline status` muestra delta respecto al baseline
- [x] **Ratcheting** — CI solo falla si las métricas empeoran respecto al baseline; deuda existente no bloquea
- [x] **Severidad configurable** en `debtector.toml` — `error` (bloquea CI) / `warning` (comenta PR) / `info` (solo reporta)
- [x] **Modo silencioso por defecto** — sin baseline configurado, primera ejecución solo reporta, no falla
- [x] **CI reporter** — salida compatible con GitHub Annotations (`::warning file=auth.py,line=14::...`) y GitLab CI

---

## Fase 2 — Análisis behavioral (git history)
*Parsear `git log` es barato. Hotspots los entiende cualquier senior en 10 segundos. Aquí está la ventaja real sobre herramientas estructurales puras.*

- [x] **Parser `git log --numstat`** — churn por módulo (commits que tocan cada archivo)
- [x] **Hotspot score** — churn × acoplamiento estructural; ranking de deuda técnica real
- [x] **Temporal coupling** — archivos que cambian juntos en commits con frecuencia > umbral, aunque no tengan import entre ellos
- [x] **Bus factor por módulo** — porcentaje de código escrito por un único autor vía `git blame`
- [x] **Integración Karajan** — interfaz JSON disponible en todos los comandos (`--json`); Karajan puede invocar `debtector report --json` directamente

---

## Fase 3 — Graph diff para PRs
*El más diferencial técnicamente. Construir cuando Fase 1+2 tengan tracción.*

- [ ] **`debtector diff <db_base> <db_pr>`** — compara dos índices SQLite y reporta el delta
- [ ] **Delta de métricas por PR** — qué módulos empeoraron, qué mejoraron, nuevos ciclos, nuevos god modules
- [ ] **GitHub Action `debtector-action`** — indexa rama base + rama PR y publica comentario con el diff

---

## Fase 4 — Features avanzadas
*Solo si las fases anteriores tienen tracción.*

- [ ] **Architectural layer violations** — usuario define capas en `debtector.toml`; analizador detecta imports que violan el sentido
- [ ] **Abstractness + distancia a la secuencia principal** — ratio clases abstractas, zona del dolor, zona inútil (precisión limitada en Python/JS)
- [ ] **Tendencias históricas** — evolución del acoplamiento a lo largo del tiempo

---

## Deuda técnica pendiente (no roadmap)

- [ ] **Schema migrations** — tabla `metadata` con `schema_version` + migración automática al abrir DB antigua
- [ ] **Más lenguajes** — Go, Rust, Java (Tree-sitter los soporta; solo falta escribir el parser siguiendo `base.py`)

---

## Congelado — no desarrollar más

- **Búsqueda semántica** (`embedder.py`, `sqlite-vec`, `fastembed`) — código conservado en grupo opcional `[semantic]`; no forma parte del objetivo CI/PR

---

## Hecho

- [x] Tests unitarios — parsers Python/JS/TS, GraphStore, indexer
- [x] Fixture JS/TS equivalente a `tests/fixtures/sample.py`
- [x] `.debtectorignore` — soporte para ignorar rutas adicionales
- [x] Arista `COVERS` + `debtector untested` — símbolos sin cobertura de tests
- [x] FTS5 con BM25 y camelCase splitting — `debtector search`
- [x] Aristas `CALLS` en parsers Python y JS/TS
- [x] `debtector install-hook` — pre-commit hook de git
- [x] `debtector install-skill` — skills para Claude Code
- [x] `debtector impact` — radio de impacto de cambios
- [x] Búsqueda semántica (`sqlite-vec` + `fastembed`) — congelada, movida a `[semantic]`
