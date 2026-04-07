# CodeIndex — Documento de Contexto Completo

> Este documento contiene TODO el contexto del proyecto para continuar el desarrollo en Claude Code.

---

## 1. Qué es CodeIndex

CodeIndex es un **indexador de código fuente** que analiza repositorios, extrae su estructura (imports, clases, métodos, funciones) y la almacena en un **grafo sobre SQLite**. El objetivo es que una IA pueda entender un codebase sin leer archivos enteros, **reduciendo drásticamente el consumo de tokens**.

### El problema que resuelve

Cuando una IA necesita entender un proyecto, típicamente lee archivos enteros (exploración masiva). Un proyecto con 200 archivos Python puede tener ~50,000 líneas (~150,000 tokens). Pero para responder "¿qué hace el módulo de pagos?" solo necesitas ~500 tokens de información estructural.

### La solución

Un solo archivo `.codeindex.db` (SQLite) que almacena:
- **Nodos**: archivos, clases, funciones, métodos
- **Aristas**: imports, herencia, llamadas, containment
- **Metadatos**: hashes de archivos, timestamps

Para traversals complejos (análisis de impacto, dependencias transitivas) se usa **NetworkX** como grafo en memoria con cache invalidable.

---

## 2. Decisiones de diseño tomadas

### ¿Por qué SQLite y no una base vectorial?
- El objetivo principal es almacenar **estructura del código** (imports, clases, métodos), que es información relacional
- SQLite es un solo archivo portable que puede commitearse en el repo
- No necesita servidor ni Docker
- Para búsquedas semánticas ("lógica de autenticación") se podría añadir sqlite-vec en el futuro, pero no es prioritario

### ¿Por qué grafo sobre SQLite y no CogDB/Neo4j?
- CogDB guarda datos en un directorio con archivos binarios propios, no es un solo archivo portable
- Neo4j requiere servidor
- Un grafo se modela perfectamente con dos tablas SQL: `nodes` y `edges`
- Para traversals profundos usamos NetworkX en memoria (no CTEs recursivos)

### ¿Por qué qualified_name?
Es la "dirección completa" de cualquier símbolo en todo el codebase:
```
src/auth/service.py                              → El archivo
src/auth/service.py::UserService                 → Una clase
src/auth/service.py::UserService.get_user        → Un método
src/auth/service.py::create_app                  → Una función top-level
```
Sin esto, habría ambigüedad entre funciones con el mismo nombre en archivos distintos.

### Patrón de escritura atómica por archivo
Cuando un archivo cambia, se borran TODOS sus nodos y aristas y se re-insertan dentro de una transacción. Si algo falla, nada cambia. Esto simplifica la indexación incremental.

### NetworkX como cache en memoria
SQLite persiste los datos. Para consultas de grafo complejas (BFS, impacto, dependencias transitivas), se carga todo en un DiGraph de NetworkX. El cache se invalida automáticamente tras cada escritura.

---

## 3. Arquitectura actual

```
codeindex/
├── pyproject.toml
├── src/
│   └── codeindex/
│       ├── __init__.py          # v0.2.0
│       ├── __main__.py          # python -m codeindex
│       ├── models.py            # NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
│       ├── graph_store.py       # GraphStore: SQLite + NetworkX cache
│       ├── indexer.py           # Orquestador: recorre archivos, detecta cambios, parsea
│       ├── cli.py               # Comandos: index, search, summary, impact, imports, status, callers
│       └── parser/
│           ├── __init__.py      # ParserRegistry
│           ├── base.py          # LanguageParser (abstracta)
│           ├── python_parser.py # Parser Python con Tree-sitter
│           └── js_parser.py     # Parser JS/TS con Tree-sitter
└── tests/
    └── fixtures/
        └── sample.py            # Fixture de test
```

---

## 4. Schema de la base de datos

```sql
CREATE TABLE nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,        -- File, Class, Function, Method
    name            TEXT NOT NULL,        -- "get_user"
    qualified_name  TEXT NOT NULL UNIQUE, -- "src/app.py::UserService.get_user"
    file_path       TEXT NOT NULL,        -- "src/app.py"
    line_start      INTEGER DEFAULT 0,
    line_end        INTEGER DEFAULT 0,
    language        TEXT DEFAULT '',      -- "python", "javascript", "typescript"
    parent_name     TEXT,                 -- "UserService" (para métodos)
    signature       TEXT,                 -- "def get_user(self, id: int) -> User"
    docstring       TEXT,
    decorators      TEXT DEFAULT '[]',    -- JSON array
    file_hash       TEXT DEFAULT '',      -- SHA-256 del archivo
    extra           TEXT DEFAULT '{}',    -- JSON libre
    updated_at      REAL NOT NULL
);

CREATE TABLE edges (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,     -- CONTAINS, IMPORTS_FROM, HAS_METHOD, INHERITS, CALLS, DEPENDS_ON
    source_qualified    TEXT NOT NULL,     -- qualified_name del origen
    target_qualified    TEXT NOT NULL,     -- qualified_name del destino
    file_path           TEXT NOT NULL,
    line                INTEGER DEFAULT 0,
    extra               TEXT DEFAULT '{}',
    updated_at          REAL NOT NULL
);

CREATE TABLE metadata (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
```

### Índices
```sql
idx_nodes_qualified ON nodes(qualified_name)
idx_nodes_file ON nodes(file_path)
idx_nodes_kind ON nodes(kind)
idx_nodes_name ON nodes(name)
idx_edges_source ON edges(source_qualified)
idx_edges_target ON edges(target_qualified)
idx_edges_kind ON edges(kind)
idx_edges_file ON edges(file_path)
```

---

## 5. Tipos de nodos y aristas

### NodeKind (enum)
| Valor | Descripción |
|-------|-------------|
| `File` | Un archivo fuente |
| `Class` | Una clase |
| `Function` | Función top-level |
| `Method` | Método dentro de una clase |

### EdgeKind (enum)
| Valor | Significado | Ejemplo |
|-------|-------------|---------|
| `CONTAINS` | Archivo contiene símbolo | `app.py` → `app.py::UserService` |
| `HAS_METHOD` | Clase tiene método | `::UserService` → `::UserService.get_user` |
| `IMPORTS_FROM` | Archivo importa módulo | `app.py` → `flask` |
| `INHERITS` | Clase hereda de otra | `::AdminService` → `UserService` |
| `CALLS` | Función llama a función | (aún no implementado en parsers) |
| `DEPENDS_ON` | Dependencia genérica | (para uso futuro) |

---

## 6. Modelos de datos (models.py)

### NodeInfo (input al GraphStore)
```python
@dataclass
class NodeInfo:
    kind: str                          # NodeKind.CLASS
    name: str                          # "UserService"
    qualified_name: str                # "src/app.py::UserService"
    file_path: str                     # "src/app.py"
    line_start: int = 0
    line_end: int = 0
    language: str = ""                 # "python"
    parent_name: str | None = None     # "UserService" (para métodos)
    signature: str | None = None       # "class UserService"
    docstring: str | None = None
    decorators: list[str] = []
    extra: dict = {}
```

### EdgeInfo (input al GraphStore)
```python
@dataclass
class EdgeInfo:
    kind: str              # EdgeKind.IMPORTS_FROM
    source: str            # qualified_name del origen
    target: str            # qualified_name del destino
    file_path: str
    line: int = 0
    extra: dict = {}
```

### GraphNode / GraphEdge (output del GraphStore)
Igual que los anteriores pero con `id: int` y `file_hash` adicionales.

### Función helper
```python
def make_qualified_name(file_path, name, kind, parent_name=None) -> str:
    # File     → "src/app.py"
    # Class    → "src/app.py::UserService"
    # Method   → "src/app.py::UserService.get_user"
    # Function → "src/app.py::create_app"
```

---

## 7. GraphStore (graph_store.py) — API completa

### Escritura
```python
store = GraphStore(".codeindex.db")

# Almacenar atómicamente un archivo completo
store.store_file(file_path, nodes, edges, file_hash)

# Eliminar un archivo del índice
store.remove_file(file_path)

# Metadatos clave-valor
store.set_metadata("last_indexed", "2025-01-01")
```

### Lectura directa (SQL)
```python
store.get_file_hash(file_path) -> str | None
store.get_node(qualified_name) -> GraphNode | None
store.get_nodes_by_file(file_path) -> list[GraphNode]
store.get_all_files() -> list[str]
store.search_nodes("user service", kind="Class") -> list[GraphNode]
store.search_imports("flask") -> list[dict]
store.get_file_summary(file_path) -> dict | None
```

### Lectura de grafo (NetworkX)
```python
store.get_outgoing(qualified_name, edge_kind=None) -> list[GraphEdge]
store.get_incoming(qualified_name, edge_kind=None) -> list[GraphEdge]
store.callers_of(qualified_name) -> list[GraphNode]
store.callees_of(qualified_name) -> list[GraphNode]
store.get_impact_radius(changed_files, max_depth=2) -> dict
store.get_dependency_chain(qualified_name, max_depth=5) -> list[list[str]]
```

### Estadísticas
```python
store.get_stats() -> GraphStats
# GraphStats: total_nodes, total_edges, nodes_by_kind, edges_by_kind, languages, files_count
```

---

## 8. Parsers

### Lenguajes soportados
- **Python** (.py) — PythonParser
- **JavaScript/TypeScript** (.js, .jsx, .ts, .tsx) — JavaScriptParser

### Qué extrae cada parser
Ambos parsers usan Tree-sitter y producen `(list[NodeInfo], list[EdgeInfo])`:

1. **Nodo File** para el archivo en sí
2. **Nodos Class/Function/Method** para cada símbolo
3. **Aristas CONTAINS** (archivo → clase, archivo → función)
4. **Aristas HAS_METHOD** (clase → método)
5. **Aristas IMPORTS_FROM** (archivo → módulo importado)
6. **Aristas INHERITS** (clase → clase base)
7. **Signatures** y **docstrings** cuando están disponibles

### Qué NO extrae aún (TODO)
- **Aristas CALLS** (qué funciones llama cada función) — requiere análisis más profundo del AST
- **Variables y constantes** — no se indexan como nodos
- **Type hints como aristas** — `def f(x: User)` no genera arista hacia `User`

---

## 9. Indexer (indexer.py)

El Indexer conecta parsers con el GraphStore:

1. Recorre el directorio del proyecto
2. Filtra por extensiones soportadas e ignora dirs como `node_modules`, `.venv`, etc.
3. Para cada archivo: compara hash actual vs almacenado
4. Si cambió: parsea → reescribe rutas a relativas → `store.store_file()`
5. Si un archivo fue eliminado: `store.remove_file()`

### Directorios ignorados por defecto
`.git`, `__pycache__`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `.idea`, `.vscode`, y más.

---

## 10. CLI (cli.py)

```bash
# Indexar un proyecto
codeindex index ./mi-proyecto

# Buscar símbolos
codeindex search "UserService"
codeindex search "get_user" --kind Method

# Resumen de un archivo (nodos + aristas)
codeindex summary src/auth/service.py

# Análisis de impacto: ¿qué se rompe si cambio estos archivos?
codeindex impact src/auth/service.py src/models/user.py --depth 3

# ¿Qué archivos importan un módulo?
codeindex imports flask

# Estadísticas del índice
codeindex status

# ¿Quién llama a un símbolo?
codeindex callers "src/auth/service.py::UserService.get_user"
```

---

## 11. Dependencias

```toml
[project]
dependencies = [
    "tree-sitter-language-pack>=1.0",   # Parsing multi-lenguaje (170+ lenguajes)
    "networkx>=3.0",                     # Grafo en memoria para traversals
    "structlog>=24.0",                   # Logging estructurado
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov",
    "ruff>=0.4",
    "bandit[toml]>=1.7",
    "commitizen>=3.0",
    "pre-commit>=3.0",
]
```

### Gestor de paquetes: uv
- `uv` es el gestor de paquetes del proyecto (reemplaza pip/virtualenv)
- Comandos habituales:
  ```bash
  uv sync                    # instalar dependencias
  uv sync --dev              # instalar con deps de dev
  uv run pytest              # ejecutar tests
  uv run codeindex index .   # ejecutar CLI
  uv add <paquete>           # añadir dependencia
  ```

---

## 12. Principios de diseño

### Principios generales
- **SOLID**: Single responsibility, Open/closed, Liskov substitution, Interface segregation, Dependency inversion
- **KISS**: La solución más simple que funciona
- **YAGNI**: No implementar nada que no sea necesario ahora mismo
- **Decoupled code**: Módulos sin dependencias circulares; parsers, store y CLI son intercambiables

### TDD — Test-Driven Development
- **Escribir el test antes que la implementación** en todo código nuevo
- Ciclo: Red → Green → Refactor
- Los tests son la especificación ejecutable del comportamiento esperado

---

## 13. Code Style

- **Ruff** para linting y formateo (`line-length = 100`)
- **Google style docstrings** en todas las funciones y clases públicas
- **Type hints** en todos los parámetros y tipos de retorno
- Imports ordenados por ruff (isort integrado)

Configuración ruff en `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "C4", "UP"]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

---

## 14. Logging (structlog)

```python
import structlog
log = structlog.get_logger()

# Adjuntar contexto que se propaga a todos los logs siguientes
log = log.bind(file_path="src/app.py", operation="index")
log.info("indexing_started")
log.info("node_stored", kind="Class", name="UserService")
log.warning("parse_warning", reason="no docstring")
log.error("index_failed", exc_info=True)
```

### Configuración dev vs prod
- **Dev** (`CODEINDEX_LOG_JSON=false`): salida coloreada en consola
- **Prod** (`CODEINDEX_LOG_JSON=true`): JSON lines para ingestión por sistemas de log
- Todos los pasos del indexer, parsers y store deben tener logs

---

## 15. CI/CD

### Pre-commit hooks (local, en cada commit)
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff          # linter
      - id: ruff-format   # formatter

  - repo: https://github.com/commitizen-tools/commitizen
    hooks:
      - id: commitizen    # valida conventional commits

  - repo: https://github.com/PyCQA/bandit
    hooks:
      - id: bandit        # seguridad
```

### Reglas CI
| Evento | Checks obligatorios |
|--------|---------------------|
| `commit` | ruff (linter) + commitizen (conventional commits) |
| `push` | todos los tests (`pytest`) |
| `pull_request` | todos los tests + ruff + bandit |

### Conventional Commits (commitizen)
Formato: `<type>(<scope>): <description>`

Tipos válidos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

Ejemplos:
```
feat(parser): add CALLS edge extraction for Python
fix(store): handle duplicate qualified_name on re-index
test(indexer): add fixture for JS files
chore(deps): upgrade tree-sitter-language-pack to 1.1
```

---

## 16. Seguridad (bandit)

- `bandit` analiza el código Python en busca de vulnerabilidades comunes
- Configurado para correr en CI en cada PR
- Configuración en `pyproject.toml`:
```toml
[tool.bandit]
exclude_dirs = ["tests"]
skips = []      # no skip ningún check por defecto
```

---

## 17. Código de referencia que nos inspiró

Repositorio: **https://github.com/tirth8205/code-review-graph/tree/main**

El archivo que analizamos fue el `GraphStore` de este proyecto (un graph store de producción para code review con MCP). Patrones que adoptamos de él:

1. **qualified_name** como identificador único: `file_path::parent.name`
2. **Escritura atómica por archivo**: `BEGIN IMMEDIATE` → delete → insert → commit
3. **NetworkX como cache**: SQLite persiste, NetworkX computa
4. **Batch queries**: lotes de 450 para no superar el límite de variables SQLite (999)
5. **BFS bidireccional** para análisis de impacto
6. **Tabla metadata** como key-value genérico
7. **Sanitización de nombres** para evitar prompt injection

---

## 18. TODO — Lo que falta por implementar

### Prioridad alta
- [ ] **Tests**: unitarios para parsers, GraphStore, indexer
- [ ] **Fixture de JavaScript** para tests del JS parser
- [ ] **Aristas CALLS**: análisis de llamadas a funciones dentro del cuerpo de funciones/métodos
- [ ] **Verificar parsers** ejecutando contra el sample.py existente

### Prioridad media
- [ ] **Más lenguajes**: Java, Go, Rust (tree-sitter los soporta, solo falta escribir el parser)
- [ ] **Detección de exports/API pública**: distinguir funciones internas de las exportadas
- [ ] **Migración de schema**: tabla metadata con schema_version + script de migraciones
- [ ] **Watch mode**: re-indexar automáticamente cuando cambian archivos (watchdog)

### Prioridad baja (ideas futuras)
- [ ] **sqlite-vec**: añadir embeddings para búsqueda semántica sin cambiar de DB
- [ ] **MCP server**: exponer el GraphStore como herramienta MCP para Claude Code
- [ ] **Visualización**: exportar el grafo a formato compatible con D3.js o similar
- [ ] **Type hints como aristas**: `def f(x: User)` → arista USES_TYPE hacia User

---

## 19. Fixture de test existente

El archivo `tests/fixtures/sample.py` contiene un servicio Flask de ejemplo con:
- 4 imports (incluyendo relativos)
- 1 dataclass (`User`)
- 2 clases (`UserService`, `AdminService` que hereda de `UserService`)
- 5 métodos (`__init__`, `get_user`, `create_user`, `validate_email`, `deactivate_user`)
- 2 funciones top-level (`create_app`, `health_check`)

Este fixture debería producir al parsearse:
- 1 nodo File + 3 nodos Class + 5 nodos Method + 2 nodos Function = **11 nodos**
- 1 arista CONTAINS por clase/función top-level + 5 HAS_METHOD + 4 IMPORTS_FROM + 1 INHERITS = **~14 aristas**
