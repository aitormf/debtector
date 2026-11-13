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
- [x] **Hotspot score** — churn × complejidad ciclomática (Tornhill); el acoplamiento estructural se muestra como contexto. Antes: churn × acoplamiento
- [x] **Complejidad ciclomática por función** — McCabe con tree-sitter en `Function`/`Method` (`extra.complexity`), comando `debtector complexity`; `PARSER_VERSION` fuerza el reindexado cuando cambia la salida de los parsers
- [ ] **Complejidad en baseline/ratcheting** — llegará con `debtector diff`
- [x] **Temporal coupling** — archivos que cambian juntos en commits con frecuencia > umbral, aunque no tengan import entre ellos
- [x] **Bus factor por módulo** — porcentaje de código escrito por un único autor vía `git blame`
- [x] **Integración Karajan** — interfaz JSON disponible en todos los comandos (`--json`); Karajan puede invocar `debtector report --json` directamente

---

## Fase 3 — Audit (vista de auditoría)
*Segundo presenter sobre el mismo backend de Fase 1+2. Para revisión profunda por tech lead, no para PR. Mismo grafo, presentación distinta — sin nueva fuente de datos. Ver [D-0003](docs/decisions/0003-audit-as-second-surface.md).*

- [x] **LCOM4** — cohesión interna de clases vía componentes conexas en aristas CALLS método↔método dentro de la misma clase. Cada clase recibe un valor (1 = cohesiva, >1 = candidata a partir)
- [x] **Priorización de ciclos** — ordenar ciclos detectados por fan-in del nodo más expuesto del ciclo ("qué ciclo romper primero")
- [x] **Joins de testRisk** — cruces que el grafo permite y los reportes sueltos no:
  - untested × Ce alto → "untested high-coupling" (riesgo máximo en cambios futuros)
  - untested × churn alto → "untested hotspots" (deuda más probable de explotar)
  - bus factor 1 × Ca alto → "critical knowledge concentration"
- [x] **Health score agregado** — valor 0-100 + conteos por severidad (critical / high / medium / low)
- [x] **`debtector audit`** — comando opinado con 8 secciones: `summary`, `coupling`, `cycles`, `cohesion`, `testRisk`, `hotspots`, `busFactor`, `inheritance`. Top-N por dimensión por defecto. `--full` para listado completo, `--json` para consumo programático
- [x] **Schema versionado para `audit --json`** — campo `schema_version: 1` en la raíz para que consumidores externos puedan evolucionar sin romperse
- [x] **`docs/audit-schema.md`** — contrato JSON estable: shape, semántica de cada campo, ejemplos

---

## Fase 4 — Graph diff para PRs
*El más diferencial técnicamente. Construir cuando Fase 1+2+3 tengan tracción.*

- [x] **`debtector diff <db_base> <db_pr>`** — compara dos índices SQLite y reporta el delta
- [x] **Delta de métricas por PR** — qué módulos empeoraron, qué mejoraron, nuevos ciclos, nuevos god modules
- [x] **GitHub Action** (`action.yml` en este repo, D-0009) — indexa rama base + rama PR y publica un comentario único con el diff
- [ ] **Diff consciente de movimientos** — hoy `diff` identifica funciones y hotspots por ruta, así que mover o renombrar un fichero (p. ej. `cli.py` → `cli/__init__.py`, PR #42) lista cada función compleja como empeorada y mejorada a la vez, y el fichero como hotspot nuevo con el churn heredado. Emparejar funciones que desaparecen y aparecen con el mismo nombre y complejidad, y usar los renombrados de git para los hotspots
- [ ] **SDP sin fachadas de paquete** — un `__init__.py` que solo reexporta sus submódulos depende de ellos por diseño, pero cuenta como violación SDP si es más estable que el submódulo (p. ej. `audit/__init__.py` → `audit/testrisk.py`, PR #47). Ignorar las aristas de un `__init__.py` de solo reexportación hacia su propio paquete, o atribuir sus dependientes a los submódulos

---

## Fase 5 — Features avanzadas
*Solo si las fases anteriores tienen tracción.*

- [ ] **Architectural layer violations** — usuario define capas en `debtector.toml`; analizador detecta imports que violan el sentido
- [ ] **Abstractness + distancia a la secuencia principal** — ratio clases abstractas, zona del dolor, zona inútil (precisión limitada en Python/JS)
- [ ] **Tendencias históricas** — evolución del acoplamiento a lo largo del tiempo

---

## Deuda técnica pendiente (no roadmap)

- [ ] **LCOM4 con atributos compartidos** — hoy solo une métodos por `CALLS`, así que clases cohesivas (`IgnoreRules`, bases abstractas) salen con LCOM4 > 1. Añadir arista de acceso a atributos (`self.x`) en los parsers y excluir métodos abstractos/sin cuerpo; hasta entonces `cohesion` no cuenta en el health score
- [ ] **Rutas en Windows** — el indexer guarda rutas con el separador del sistema (`os.path.relpath`) pero la clasificación de tests y los patrones SQL esperan `/`; normalizar a POSIX al guardar
- [ ] **Tests como módulos al indexar `.`** — si el usuario indexa la raíz, los ficheros de test cuentan en Ca/Ce, hotspots y god modules; solo se excluyen los que llegan vía `test_paths`
- [ ] **`debtector status` cuenta los ficheros de `test_paths`** — `get_stats` los incluye en `files_count` y en los conteos por tipo
- [ ] **Clones superficiales en CI** — con `fetch-depth: 1` (el defecto de `actions/checkout`) el historial solo tiene un commit: churn, hotspots y temporal coupling salen a cero. Avisar sin bloquear al detectarlo (`git rev-parse --is-shallow-repository`) y documentar `fetch-depth: 0`; el exento de autor único ya no se aplica en ese caso
- [ ] **Gramáticas de tree-sitter descargadas en runtime** — `tree-sitter-language-pack` las baja de GitHub en el primer uso; sin red o con un 5xx de GitHub el índice falla. Empaquetarlas o documentar cómo descargarlas antes (el CI propio ya las cachea)
- [ ] **Texto de `busFactor` en `docs/audit-schema.md`** — dice «≥50% del churn» pero el código usa el 80% de las líneas de `git blame`
- [ ] **Salida humana de `audit`** — solo muestra critical y high; los hotspots puntúan como medium y no se ven
- [ ] **Cobertura real** — leer `coverage.xml` / `lcov.info` si existen; la heurística `COVERS` no ve llamadas a métodos de objetos (`service.validate()`) y deja ficheros probados como «sin cubrir»
- [ ] **Más lenguajes** — Go, Rust, Java (Tree-sitter los soporta; solo falta escribir el parser siguiendo `base.py`)

---

## Hecho

- [x] **Receta NL → archivos en README** — flujo `search` → `impact` → enriquecer con métricas, documentado sin acoplarse a ningún consumidor; decisión de no exponerlo como comando paraguas en [D-0003](docs/decisions/0003-audit-as-second-surface.md)
- [x] Tests unitarios — parsers Python/JS/TS, GraphStore, indexer
- [x] Fixture JS/TS equivalente a `tests/fixtures/sample.py`
- [x] `.debtectorignore` — soporte para ignorar rutas adicionales
- [x] Arista `COVERS` + `debtector untested` — símbolos sin cobertura de tests
- [x] FTS5 con BM25 y camelCase splitting — `debtector search`
- [x] Aristas `CALLS` en parsers Python y JS/TS
- [x] `debtector install-hook` — pre-commit hook de git
- [x] `debtector install-skill` — skills para Claude Code
- [x] `debtector impact` — radio de impacto de cambios
- [x] Búsqueda semántica (`sqlite-vec` + `fastembed`) — retirada; ver D-0001
- [x] **Schema migrations** — `GraphStore._apply_migrations` migra la DB al abrirla
