# Arquitectura de Debtector

## Visión general

Debtector analiza repositorios de código fuente, extrae su estructura (clases, funciones, métodos, imports, llamadas) y la almacena como un **grafo en SQLite**. El objetivo es **detectar acoplamiento de código en pipelines de CI y PR reviews**, dando al desarrollador contexto arquitectónico antes de mergear.

ICP: desarrollador o tech lead que usa agentes de código (Claude Code, Copilot, Codex). Los agentes generan acoplamiento oculto a una velocidad que ningún humano alcanza; codeIndex actúa como guardarraíl arquitectónico en el pipeline.

Ver [ADR-002](decisions/002-pivot-ci-coupling.md) para el contexto completo del pivote.

---

## Módulos

```
src/debtector/
├── models.py         # Tipos de datos: NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
├── graph_store.py    # Persistencia: SQLite + NetworkX cache en memoria
├── indexer.py        # Orquestación: recorre archivos, detecta cambios, llama a parsers
├── metrics.py        # Ca, Ce, inestabilidad, ciclos, god modules, herencia
├── config.py         # Carga y valida debtector.toml (umbrales y severidad)
├── cli.py            # CLI: index, search, summary, impact, imports, callers,
│                     #       untested, status, metrics, baseline
├── utils.py          # Utilidades compartidas: is_test_file()
├── logging.py        # Configuración structlog (dev coloreado / prod JSON)
├── embedder.py       # [CONGELADO] Embeddings semánticos — no desarrollar más
│                     #   Disponible con uv add 'debtector[semantic]'
└── parser/
    ├── base.py           # LanguageParser — clase abstracta
    ├── python_parser.py  # PythonParser — Tree-sitter Python
    └── js_parser.py      # JavaScriptParser — Tree-sitter JS/TS
```

### Responsabilidades

| Módulo | Responsabilidad |
|---|---|
| `models.py` | Define los tipos de entrada (`NodeInfo`, `EdgeInfo`) y salida (`GraphNode`, `GraphEdge`) sin dependencias internas |
| `graph_store.py` | Única fuente de verdad. Escribe en SQLite, mantiene un DiGraph de NetworkX como cache para traversals |
| `indexer.py` | Recorre el sistema de archivos, detecta cambios por SHA-256, delega el parseo y llama a `GraphStore.store_file()`. Genera aristas COVERS tras cada indexación (no-fatal) |
| `metrics.py` | Computa métricas de acoplamiento sobre el grafo: Ca, Ce, inestabilidad, ciclos (Tarjan), god modules (p90), profundidad de herencia |
| `config.py` | Lee `debtector.toml` con `tomllib` (stdlib). Expone `DebtectorConfig` con umbrales y severidades configurables |
| `embedder.py` | **[Congelado]** Convierte nodos a texto y genera vectores float32 con fastembed. No desarrollar más |
| `utils.py` | Utilidades compartidas sin dependencias internas: `is_test_file()` |
| `parser/*` | Transforman un archivo fuente en `(list[NodeInfo], list[EdgeInfo])` usando Tree-sitter. Sin acceso a la DB |
| `cli.py` | Traduce argumentos de línea de comandos a llamadas al GraphStore y metrics. Sin lógica de negocio propia |

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
    ├── Búsqueda léxica       → SQLite FTS5              (debtector search)
    ├── Lookup directo        → SQLite SQL                (summary, callers, imports)
    ├── Traversal de impacto  → NetworkX                  (debtector impact)
    ├── Métricas acoplamiento → metrics.py sobre el grafo (debtector metrics)
    └── Baseline / ratcheting → baseline.json + delta     (debtector baseline)
```

> La búsqueda semántica (`sqlite-vec` KNN) está congelada. Ver sección [Semántica congelada](#semántica-congelada).

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
    name, qualified_name, signature, docstring,
    content='nodes', content_rowid='id'
);
```

Ranking BM25 con camelCase splitting: `"UserService"` → tokens `user`, `service`, `userservice`. Cada término se expande con `*` para prefix matching.

---

## Persistencia del baseline

`.debtector/baseline.json` — snapshot de métricas de acoplamiento generado con `debtector baseline save`. Se commitea al repo; es la referencia compartida para el ratcheting en CI.

```json
{
  "saved_at": "2026-04-24T10:00:00+00:00",
  "modules": [
    { "file_path": "src/auth.py", "fan_in": 8.0, "fan_out": 3.0, "instability": 0.2727 }
  ],
  "cycles": [["src/auth.py", "src/user.py"]],
  "god_modules": ["src/models.py"]
}
```

El `.debtector/.gitignore` es gestionado por codeIndex (siempre sobreescrito): ignora todo excepto `baseline.json` y el propio `.gitignore`.

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
| `USES_TYPE` | Función referencia un tipo en sus type hints (peso 1.0 en Ca/Ce) | `app.py::get_user` → `User` |
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
| Fan-in (Ca) | Suma ponderada de aristas IMPORTS_FROM + USES_TYPE entrantes | ≥ 0 |
| Fan-out (Ce) | Suma ponderada de aristas IMPORTS_FROM + USES_TYPE salientes | ≥ 0 |
| Inestabilidad (I) | Ce / (Ca + Ce) | [0, 1] |

Pesos: `IMPORTS_FROM` = 1.0, `USES_TYPE` = 1.0. Ambos pesos son constantes públicas en `metrics.py` (`IMPORTS_FROM_WEIGHT`, `USES_TYPE_WEIGHT`) para facilitar ajustes en experimentos.

### Ciclos

Detección mediante el **algoritmo de Tarjan iterativo** (evita RecursionError en cadenas largas) sobre aristas `IMPORTS_FROM` y `CALLS`. Devuelve SCCs de tamaño > 1.

### God modules

Outlier estadístico en Ca: módulos cuyo fan-in supera el **percentil 90** del proyecto (umbral relativo, no absoluto). Configurable en `debtector.toml`.

### Herencia

Profundidad (camino más largo desde la raíz) y número de hijos directos, traversando aristas `INHERITS`. Soporta herencia cross-file; corta ciclos.

---

## Configuración (`debtector.toml`)

Archivo opcional en la raíz del proyecto. Usa `tomllib` de la stdlib (Python 3.12+):

```toml
[metrics.thresholds]
god_module_percentile = 90    # percentil Ca para god module (default: 90)
instability_threshold = 0.8   # I >= umbral → aviso (default: 0.8)
max_inheritance_depth = 5     # profundidad máxima de herencia (default: 5)
max_children          = 10    # hijos directos máximos (default: 10)

[metrics.severity]
cycles      = "error"    # error | warning | info (default: error)
god_modules = "warning"  # (default: warning)
instability = "warning"  # (default: warning)
inheritance = "info"     # (default: info)
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
- **Regresión de inestabilidad** > `_INSTABILITY_TOLERANCE` (0.05) → según `severity.instability`
- **Sin baseline** → siempre exit code 0 (modo silencioso)

### CI reporter

`--reporter github` emite GitHub Actions Annotations:
```
::error file=src/auth.py,line=1::Ciclo de importación: src/auth.py → src/user.py
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

## Semántica congelada

`embedder.py`, `sqlite-vec` y `fastembed` están congelados: el código existe pero no se desarrollará más. No forman parte del objetivo CI/PR.

- Disponibles como dependencia opcional: `uv add 'debtector[semantic]'`
- El comando `debtector semantic` devuelve un error con mensaje de deprecación
- Los tests de embeddings siguen existiendo pero no cubren el objetivo actual

Ver [ADR-002](decisions/002-pivot-ci-coupling.md) para el razonamiento completo.

---

## Parsers

Cada parser implementa `LanguageParser` (abstracta en `parser/base.py`) y recibe la ruta de un archivo, devolviendo `(list[NodeInfo], list[EdgeInfo])`.

### Qué extrae cada parser

- Nodo `File` para el archivo en sí
- Nodos `Class`, `Function`, `Method` para cada símbolo
- Aristas `CONTAINS`, `HAS_METHOD`, `IMPORTS_FROM`, `INHERITS`, `CALLS`
- Aristas `USES_TYPE` desde type hints en firmas (solo nombres con inicial mayúscula)
- `signature` y `docstring` cuando están disponibles

### Lenguajes soportados

| Lenguaje | Extensiones | Parser |
|---|---|---|
| Python | `.py` | `PythonParser` (Tree-sitter) |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | `JavaScriptParser` (Tree-sitter) |

---

## Directorios ignorados en indexación

`.git`, `__pycache__`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `.idea`, `.vscode`

Soporte adicional para `.debtectorignore` (gitignore-style).

---

## Decisiones de arquitectura

| ADR | Decisión |
|---|---|
| [001](decisions/001-semantic-search.md) | FTS5 + sqlite-vec + fastembert para búsqueda semántica (implementado, luego congelado) |
| [002](decisions/002-pivot-ci-coupling.md) | Pivote: de navegación para IA a análisis de acoplamiento para CI/PR |
