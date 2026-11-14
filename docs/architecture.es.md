# Arquitectura de Debtector

[Read in English](architecture.md)

## Visión general

Debtector analiza repositorios de código fuente, extrae su estructura (clases, funciones, métodos, imports, llamadas) y la almacena como un **grafo en SQLite**. El objetivo es **detectar acoplamiento de código en pipelines de CI y PR reviews**, dando al desarrollador contexto arquitectónico antes de mergear.

ICP: desarrollador o tech lead que usa agentes de código (Claude Code, Copilot, Codex). Los agentes generan acoplamiento oculto a una velocidad que ningún humano alcanza; Debtector actúa como guardarraíl arquitectónico en el pipeline.

Ver [D-0002](decisions/0002-pivot-ci-coupling.md) para el contexto completo del pivote.

---

## Módulos

```
src/debtector/
├── models.py         # Tipos de datos: NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
├── graph_store.py    # Persistencia: SQLite + FTS5 + NetworkX cache en memoria; clasificación de tests
├── indexer.py        # Orquestación: recorre archivos, detecta cambios, llama a parsers
├── metrics.py        # Ca, Ce, inestabilidad, ciclos, god modules, SDP, herencia
├── git_history.py    # Análisis behavioral: churn, hotspots, temporal coupling, bus factor
├── diff.py           # Diff arquitectónico entre dos índices (base vs. PR)
├── config.py         # Carga y valida debtector.toml (umbrales y severidad)
├── utils.py          # Utilidades compartidas: is_test_file()
├── logging.py        # Configuración structlog (dev coloreado / prod JSON)
├── cli/              # Paquete CLI, un módulo por grupo de comandos (D-0011)
│   ├── app.py            # argparse y despacho
│   ├── common.py         # helpers compartidos (store, raíz del índice, test paths, salida)
│   ├── graph.py          # index, search, summary, impact, imports, status, callers
│   ├── coupling.py       # coupling (y el alias obsoleto metrics)
│   ├── baseline.py       # baseline save / status
│   ├── reporters.py      # anotaciones de GitHub e informe de GitLab
│   ├── quality.py        # complexity, untested, audit
│   ├── git.py            # hotspots, temporal-coupling, bus-factor, git-coupling
│   ├── report.py         # report
│   └── pr_diff.py        # diff
├── audit/            # Superficie audit (D-0003): health score, LCOM4, testRisk, prioridad de ciclos, complejidad
├── render/
│   └── diff_markdown.py  # Markdown del diff para el comentario de PR
└── parser/
    ├── base.py           # LanguageParser — clase abstracta
    ├── complexity.py     # Complejidad ciclomática (McCabe) sobre árboles tree-sitter (D-0004)
    ├── python_parser.py  # PythonParser — Tree-sitter Python
    └── js_parser.py      # JavaScriptParser — Tree-sitter JS/TS
```

### Responsabilidades

| Módulo | Responsabilidad |
|---|---|
| `models.py` | Define los tipos de entrada (`NodeInfo`, `EdgeInfo`) y salida (`GraphNode`, `GraphEdge`) sin dependencias internas |
| `graph_store.py` | Única fuente de verdad. Escribe en SQLite, mantiene un DiGraph de NetworkX como cache para traversals |
| `indexer.py` | Recorre el sistema de archivos, detecta cambios por SHA-256, delega el parseo y llama a `GraphStore.store_file()`. Genera aristas COVERS tras cada indexación (no-fatal) |
| `metrics.py` | Computa métricas de acoplamiento **estructural** sobre el grafo: Ca, Ce, inestabilidad, ciclos (Tarjan), god modules (p90), violaciones SDP, profundidad de herencia |
| `git_history.py` | Computa métricas de acoplamiento **behavioral** sobre el historial git: churn (`git log --numstat`), hotspot score, temporal coupling, bus factor (`git blame`). Solo lectura; no escribe en DB |
| `diff.py` | Compara dos índices con las reglas de `baseline status` (D-0008) y decide si el resultado bloquea CI (`blocks_ci`). Schema en [diff-schema.md](diff-schema.md) |
| `audit/` | Segundo presentador sobre el mismo grafo (D-0003): health score, LCOM4, testRisk, prioridad de ciclos, complejidad de funciones. Schema en [audit-schema.md](audit-schema.md) |
| `config.py` | Lee `debtector.toml` con `tomllib` (stdlib). Expone `DebtectorConfig` con umbrales y severidades configurables |
| `utils.py` | Utilidades compartidas sin dependencias internas: `is_test_file()` |
| `parser/*` | Transforman un archivo fuente en `(list[NodeInfo], list[EdgeInfo])` usando Tree-sitter. Sin acceso a la DB |
| `cli/` | Traduce argumentos de línea de comandos a llamadas al GraphStore, metrics y git_history. Sin lógica de negocio propia. Auto-indexa silenciosamente antes de cada comando de análisis |

---

## Flujo de datos

### Indexación

```
Archivo fuente
    │
    ▼
Indexer — detecta cambio por SHA-256
    │
    ▼
Parser (Tree-sitter) ──→ (list[NodeInfo], list[EdgeInfo])
    │                         incl. USES_TYPE desde type hints
    ▼
GraphStore.store_file()
    ├── SQLite  (persistencia)
    └── NetworkX DiGraph  (cache invalidable para traversals)
```

### Consulta y análisis

```
CLI / CI pipeline
    │
    ├── Auto-index silencioso → Indexer (SHA-256, no-op si sin cambios)
    │
    ├── Búsqueda léxica       → SQLite FTS5              (debtector search)
    ├── Lookup directo        → SQLite SQL                (summary, callers, imports)
    ├── Traversal de impacto  → NetworkX                  (debtector impact)
    ├── Acoplamiento struct.  → metrics.py + grafo        (debtector coupling)
    ├── Acoplamiento behav.   → git_history.py + git      (debtector git-coupling)
    │     ├── churn           → git log --numstat
    │     ├── hotspots        → churn × complejidad ciclomática
    │     ├── temporal coupl. → git log --name-only, pares co-cambiantes
    │     └── bus factor      → git blame --line-porcelain
    ├── Informe completo      → coupling + git-coupling   (debtector report)
    ├── Audit                 → audit/ + metrics + git    (debtector audit)
    ├── Baseline / ratcheting → baseline.json + delta     (debtector baseline)
    └── Diff de PR            → diff.py, ref base indexada en un worktree temporal (debtector diff)
```

---

## Schema SQLite

El índice vive en `.debtector/index.db`. Tres tablas relacionales:

```sql
CREATE TABLE nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,         -- File | Class | Function | Method
    name            TEXT NOT NULL,         -- "get_user"
    qualified_name  TEXT NOT NULL UNIQUE,  -- "src/app.py::UserService.get_user"
    file_path       TEXT NOT NULL,         -- "src/app.py"
    line_start      INTEGER DEFAULT 0,
    line_end        INTEGER DEFAULT 0,
    language        TEXT DEFAULT '',       -- "python" | "javascript" | "typescript"
    parent_name     TEXT,                  -- "UserService" (solo para Method)
    signature       TEXT,                  -- "def get_user(self, id: int) -> User"
    docstring       TEXT,
    decorators      TEXT DEFAULT '[]',     -- JSON array
    file_hash       TEXT DEFAULT '',       -- SHA-256 del archivo fuente
    extra           TEXT DEFAULT '{}',     -- JSON libre para extensiones futuras
    updated_at      REAL NOT NULL
);

CREATE TABLE edges (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    kind              TEXT NOT NULL,       -- ver EdgeKind más abajo
    source_qualified  TEXT NOT NULL,       -- qualified_name del origen
    target_qualified  TEXT NOT NULL,       -- qualified_name del destino
    file_path         TEXT NOT NULL,
    line              INTEGER DEFAULT 0,
    extra             TEXT DEFAULT '{}',
    updated_at        REAL NOT NULL
);

CREATE TABLE metadata (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
```

### Índices

```sql
idx_nodes_qualified  ON nodes(qualified_name)
idx_nodes_file       ON nodes(file_path)
idx_nodes_kind       ON nodes(kind)
idx_nodes_name       ON nodes(name)
idx_edges_source     ON edges(source_qualified)
idx_edges_target     ON edges(target_qualified)
idx_edges_kind       ON edges(kind)
idx_edges_file       ON edges(file_path)
```

### FTS5

```sql
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    node_id UNINDEXED,
    name, qualified_name, signature, docstring,
    tokenize = 'unicode61'
);
```

Ranking BM25 con camelCase splitting: `"UserService"` → tokens `user`, `service`, `userservice`. Cada término se expande con `*` para prefix matching.

---

## Persistencia del baseline

`.debtector/baseline.json` — snapshot de métricas de acoplamiento generado con `debtector baseline save`. Se commitea al repo; es la referencia compartida para el ratcheting en CI.

```json
{
  "metrics_version": 12,
  "saved_at": "2026-04-24T10:00:00+00:00",
  "modules": [
    { "file_path": "src/auth.py", "fan_in": 8.0, "fan_out": 3.0, "instability": 0.2727 }
  ],
  "cycles": [["src/auth.py", "src/user.py"]],
  "god_modules": ["src/models.py"],
  "sdp_violations": [{ "source": "src/auth.py", "target": "src/user.py" }],
  "complexity": { "medium": 21, "functions": { "src/auth.py::login": 24 } }
}
```

`metrics_version` es la versión de las métricas de acoplamiento (D-0014): un baseline guardado con otra versión no compara god modules, SDP ni inestabilidad. `complexity` guarda las funciones en o por encima de `complexity_medium` (D-0019).

El `.debtector/.gitignore` es gestionado por Debtector (siempre sobreescrito): ignora todo excepto `baseline.json` y el propio `.gitignore`.

---

## Tipos de nodos y aristas

### NodeKind

| Valor | Descripción |
|---|---|
| `File` | Un archivo fuente indexado |
| `Class` | Definición de clase |
| `Function` | Función top-level |
| `Method` | Método dentro de una clase |

### EdgeKind

| Valor | Significado | Ejemplo |
|---|---|---|
| `CONTAINS` | Archivo contiene símbolo top-level | `app.py` → `app.py::UserService` |
| `HAS_METHOD` | Clase tiene método | `app.py::UserService` → `app.py::UserService.get_user` |
| `IMPORTS_FROM` | Archivo importa módulo o símbolo | `app.py` → `flask` |
| `INHERITS` | Clase hereda de otra | `app.py::AdminService` → `UserService` |
| `CALLS` | Función/método llama a otro símbolo | `app.py::create_app` → `app.py::UserService.__init__` |
| `COVERS` | Test ejerce a símbolo de producción | `tests/test_auth.py::test_login` → `src/auth.py::login` |
| `USES_TYPE` | Función referencia un tipo en sus type hints (no cuenta en Ca/Ce, D-0012) | `app.py::get_user` → `User` |
| `DEPENDS_ON` | Dependencia genérica (uso futuro) | — |

---

## qualified_name

Identificador único de cualquier símbolo en todo el codebase:

```
src/auth/service.py                        → File
src/auth/service.py::AuthService           → Class
src/auth/service.py::AuthService.validate  → Method
src/auth/service.py::create_app            → Function
```

---

## Métricas de acoplamiento (Fase 1)

### Fan-in / Fan-out / Inestabilidad

| Métrica | Definición | Rango |
|---|---|---|
| Fan-in (Ca) | Módulos internos distintos que importan este módulo (IMPORTS_FROM) | ≥ 0 |
| Fan-out (Ce) | Módulos internos distintos que importa este módulo (IMPORTS_FROM) | ≥ 0 |
| Inestabilidad (I) | Ce / (Ca + Ce) | [0, 1] |

Un módulo solo se marca **inestable** si es el destino de una violación del Stable Dependencies Principle: una arista `IMPORTS_FROM` `A → B` entre módulos indexados con `I(B) > I(A) + sdp_margin`. Una I alta en una hoja es normal y no se marca. Un **god module** necesita Ca por encima del `god_module_percentile` **y** `Ca >= god_module_min_ca`.

Solo cuentan las aristas `IMPORTS_FROM` que se resuelven a un fichero del índice (D-0012): los imports de la librería estándar y de terceros, los imports repetidos del mismo módulo y las aristas `USES_TYPE` no cuentan. Los imports absolutos de Python se resuelven desde la raíz del paquete (D-0016) y `from X import a` depende del submódulo `X.a` si existe (D-0018). Los ficheros de test no son módulos ni dependientes (D-0015). Las fachadas puras de paquete (`__init__.py` o `index.*` de JS/TS sin clases ni funciones) no participan en las violaciones SDP (D-0017).

### Ciclos

Detección mediante el **algoritmo de Tarjan iterativo** (evita RecursionError en cadenas largas) sobre aristas `IMPORTS_FROM` y `CALLS`. Devuelve SCCs de tamaño > 1.

### God modules

Outlier estadístico en Ca: módulos cuyo fan-in supera el **percentil 90** del proyecto **y** alcanza `god_module_min_ca` (10). Ambos configurables en `debtector.toml`.

### Herencia

Profundidad (camino más largo desde la raíz) y número de hijos directos, traversando aristas `INHERITS`. Soporta herencia cross-file; corta ciclos.

---

## Métricas behavioral (Fase 2)

### Churn

Número de commits distintos que tocan cada archivo, calculado con `git log --numstat`. Los archivos binarios se cuentan pero sus líneas se registran como 0. Acepta filtro `--since` (e.g. `"6 months ago"`).

### Hotspot score

`churn × complejidad` — combina la actividad histórica con la complejidad del código (suma de la complejidad ciclomática de las funciones y métodos del archivo, calculada al indexar). Un archivo muy cambiado y complejo es el punto de mayor riesgo de deuda técnica; los archivos sin funciones puntúan 0. El acoplamiento estructural (`fan_in + fan_out`) se muestra aparte pero no entra en el score. Ordenado descendente.

### Temporal coupling

Pares de archivos que aparecen juntos en commits con frecuencia superior a un umbral. Detecta dependencias implícitas no visibles en el grafo de imports. Parámetros:
- `min_shared` (default: 5): mínimo de commits compartidos
- `min_ratio` (default: 0.3): `shared / min(commits_a, commits_b)` mínimo

### Bus factor

Mínimo de autores necesarios para cubrir el 80% de las líneas vigentes de un archivo, calculado con `git blame --line-porcelain`. Un bus factor de 1 indica punto único de fallo de conocimiento. Solo procesa archivos presentes en el índice.

---

## Configuración (`debtector.toml`)

Archivo opcional en la raíz del proyecto. Usa `tomllib` de la stdlib (Python 3.12+):

```toml
[metrics.thresholds]
god_module_percentile = 90    # percentil Ca para god module (default: 90)
god_module_min_ca     = 10    # Ca mínimo absoluto para god module (default: 10)
sdp_margin            = 0.1   # I(B) - I(A) mínimo para marcar A -> B como violación SDP (default: 0.1)
# instability_threshold: obsoleto, se ignora (se registra un aviso)
max_inheritance_depth = 5     # profundidad máxima de herencia (default: 5)
max_children          = 10    # hijos directos máximos (default: 10)

[metrics.severity]
cycles      = "error"    # error | warning | info (default: error)
god_modules = "warning"  # (default: warning)
instability = "warning"  # (default: warning)
inheritance = "info"     # (default: info)
complexity  = "warning"  # funciones empeoradas en diff / baseline status (default: warning)
```

**Severidades:**
- `error` → exit code 1, bloquea CI
- `warning` → reporta pero exit code 0
- `info` → silencioso, exit code 0

---

## Ratcheting CI

`debtector baseline status` compara el estado actual contra el baseline guardado:

- **Nuevos ciclos** no presentes en baseline → según `severity.cycles`
- **Nuevos god modules** → según `severity.god_modules`
- **Regresión de inestabilidad** > `INSTABILITY_TOLERANCE` (0.05, en `diff.py`) → según `severity.instability`
- **Nuevas violaciones SDP** (`A → B` con `I(B) > I(A) + sdp_margin`) → según `severity.instability`. Solo se comparan si el baseline contiene `sdp_violations`; un baseline antiguo no se marca
- **Funciones nuevas o empeoradas** con complejidad >= `complexity_medium` → según `severity.complexity`. Se omite (`complexity_skipped`) si el baseline no tiene `complexity` o se guardó con otro `complexity_medium`
- **Baseline de otra `metrics_version`** → no se comparan god modules, SDP ni inestabilidad (los ciclos sí)
- **Sin baseline** → siempre exit code 0 (modo silencioso)

### CI reporter

`--reporter github` emite GitHub Actions Annotations:
```
::error file=src/auth.py,line=1::Import cycle: src/auth.py → src/user.py
```

`--reporter gitlab` emite GitLab CI section markers con ANSI.

---

## Patrones de implementación clave

### Escritura atómica por archivo

Cuando un archivo cambia, se reemplazan todos sus nodos y aristas dentro de una sola transacción:

```
BEGIN IMMEDIATE
  DELETE FROM nodes WHERE file_path = ?
  DELETE FROM edges WHERE file_path = ?
  INSERT INTO nodes ...
  INSERT INTO edges ...
COMMIT
```

Si algo falla, nada cambia. Simplifica la indexación incremental: no hay merges parciales.

### NetworkX como cache de traversal

SQLite persiste los datos. Para consultas de grafo complejas (BFS de impacto, cadenas de dependencia transitivas) se carga todo en un `DiGraph` de NetworkX en memoria. El cache se invalida automáticamente tras cada escritura.

### Batch queries de 450

SQLite tiene un límite de 999 variables por consulta. Las queries con `IN (...)` se dividen en lotes de 450 para no superarlo con margen.

### Detección de cambios por SHA-256

El Indexer compara el hash SHA-256 del archivo en disco con el almacenado en `nodes.file_hash`. Solo re-parsea los archivos que han cambiado.

### Dedup USES_TYPE en O(1)

El extractor de type hints mantiene un `set[str]` compartido por archivo (`uses_type_seen`) que se pasa a través de toda la recursión de `_extract_symbols`. Evita un scan O(F×E) de la lista de aristas por cada función.

---

## Decisiones de arquitectura

| ADR | Decisión |
|---|---|
| [D-0001](decisions/0001-semantic-search.md) | FTS5 + sqlite-vec + fastembed para búsqueda semántica (implementado, congelado y después eliminado; FTS5 se mantiene) |
| [D-0002](decisions/0002-pivot-ci-coupling.md) | Pivote: de navegación para IA a análisis de acoplamiento para CI/PR |

La lista completa y actualizada está en [decisions/README.md](decisions/README.md).
