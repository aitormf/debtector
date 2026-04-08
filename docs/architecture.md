# Arquitectura de CodeIndex

## Visión general

CodeIndex analiza repositorios de código fuente, extrae su estructura (clases, funciones, métodos, imports, llamadas) y la almacena como un **grafo en SQLite**. El objetivo es que una IA pueda consultar el grafo en lugar de leer archivos enteros, reduciendo drásticamente el consumo de tokens.

Un proyecto con 200 archivos Python puede tener ~150.000 tokens de contenido. La misma información estructural cabe en ~500 tokens de consultas al grafo.

---

## Módulos

```
src/codeindex/
├── models.py         # Tipos de datos: NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
├── graph_store.py    # Persistencia: SQLite + NetworkX cache en memoria
├── indexer.py        # Orquestación: recorre archivos, detecta cambios, llama a parsers
├── cli.py            # Interfaz CLI (Typer): index, search, summary, impact, imports, callers, status
├── logging.py        # Configuración structlog (dev coloreado / prod JSON)
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
| `indexer.py` | Recorre el sistema de archivos, detecta cambios por SHA-256, delega el parseo y llama a `GraphStore.store_file()` |
| `parser/*` | Transforman un archivo fuente en `(list[NodeInfo], list[EdgeInfo])` usando Tree-sitter. Sin acceso a la DB |
| `cli.py` | Traduce argumentos de línea de comandos a llamadas al GraphStore. Sin lógica de negocio propia |

---

## Flujo de datos

```
Archivo fuente
    │
    ▼
Indexer — detecta cambio por SHA-256
    │
    ▼
Parser (Tree-sitter) ──→ (list[NodeInfo], list[EdgeInfo])
    │
    ▼
GraphStore.store_file()
    ├── SQLite  (persistencia)
    └── NetworkX DiGraph  (cache invalidable para traversals)
```

El flujo inverso (consulta):

```
CLI / AI query
    │
    ├── Búsqueda léxica → SQLite FTS5 (search)
    ├── Lookup directo  → SQLite SQL  (summary, callers, imports)
    └── Traversal       → NetworkX    (impact, dependency chain)
```

---

## Schema SQLite

El índice vive en `.codeindex/index.db`. Tres tablas:

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
| `DEPENDS_ON` | Dependencia genérica (uso futuro) | — |

#### Aristas pendientes de diseño

| Valor propuesto | Propósito |
|---|---|
| `TESTED_BY` | Une un símbolo con el test que lo ejercita. Habilitará `codeindex untested` |
| `USES_TYPE` | Une una función con los tipos que referencia en sus type hints |

---

## qualified_name

Identificador único de cualquier símbolo en todo el codebase:

```
src/auth/service.py                        → File
src/auth/service.py::AuthService           → Class
src/auth/service.py::AuthService.validate  → Method
src/auth/service.py::create_app            → Function
```

Es la "dirección completa" que elimina la ambigüedad entre símbolos con el mismo nombre en archivos distintos. Se usa como clave primaria lógica en consultas y como referencia en aristas.

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

Si algo falla, nada cambia. Esto simplifica la indexación incremental: no hay merges parciales.

### NetworkX como cache de traversal

SQLite persiste los datos. Para consultas de grafo complejas (BFS de impacto, cadenas de dependencia transitivas) se carga todo en un `DiGraph` de NetworkX en memoria. El cache se invalida automáticamente tras cada escritura — la próxima consulta de traversal reconstruye el grafo desde SQLite.

### Batch queries de 450

SQLite tiene un límite de 999 variables por consulta. Las queries con `IN (...)` se dividen en lotes de 450 para no superarlo con margen.

### Detección de cambios por SHA-256

El Indexer compara el hash SHA-256 del archivo en disco con el almacenado en `nodes.file_hash`. Solo re-parsea los archivos que han cambiado. Los archivos eliminados se detectan por diferencia entre el conjunto en disco y el conjunto en DB.

---

## Parsers

Cada parser implementa `LanguageParser` (abstracta en `parser/base.py`) y recibe la ruta de un archivo, devolviendo `(list[NodeInfo], list[EdgeInfo])`.

### Qué extrae cada parser

- Nodo `File` para el archivo en sí
- Nodos `Class`, `Function`, `Method` para cada símbolo
- Aristas `CONTAINS` (archivo → símbolo top-level)
- Aristas `HAS_METHOD` (clase → método)
- Aristas `IMPORTS_FROM` (archivo → módulo importado)
- Aristas `INHERITS` (clase → clase base)
- Aristas `CALLS` (función/método → símbolo llamado)
- `signature` y `docstring` cuando están disponibles

### Lenguajes soportados

| Lenguaje | Extensiones | Parser |
|---|---|---|
| Python | `.py` | `PythonParser` (Tree-sitter) |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | `JavaScriptParser` (Tree-sitter) |

---

## Directorios ignorados en indexación

`.git`, `__pycache__`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `.idea`, `.vscode`

Soporte para `.codeindexignore` pendiente (ver [`TODO.md`](../TODO.md)).

---

## Decisiones de arquitectura

Ver [`docs/decisions/`](decisions/) para los ADRs formales.

| ADR | Decisión |
|---|---|
| [001](decisions/001-semantic-search.md) | FTS5 (fase 1) + sqlite-vec + fastembed (fase 2) para búsqueda semántica |
