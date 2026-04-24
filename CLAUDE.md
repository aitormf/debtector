# CLAUDE.md — CodeIndex

## Qué es este proyecto

CodeIndex indexa repositorios de código fuente y almacena su estructura (clases, funciones, métodos, imports, llamadas) como un grafo en SQLite. El objetivo es **detectar acoplamiento de código en pipelines de CI y PR reviews**, dando al desarrollador contexto arquitectónico antes de mergear.

ICP: desarrollador o tech lead que usa agentes de código (Claude Code, Copilot, Codex). Los agentes generan acoplamiento oculto a una velocidad que ningún humano alcanza; codeIndex actúa como guardarraíl arquitectónico en el pipeline.

El índice vive en `.codeindex/index.db`. El baseline de métricas vive en `.codeindex/baseline.json` (commiteado al repo). Los logs van a `.codeindex/codeindex.log`, nunca a stdout.

---

## Gestor de paquetes: uv (nunca pip)

```bash
uv sync --dev              # instalar dependencias incluyendo dev
uv run pytest              # ejecutar tests
uv run codeindex index .   # ejecutar CLI
uv add <paquete>           # añadir dependencia
```

---

## Comandos de desarrollo

```bash
uv run pytest                        # tests
uv run ruff check .                  # linter
uv run ruff format .                 # formatter
uv run bandit -r src/                # seguridad
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg  # instalar hooks locales
```

---

## Arquitectura

```
src/codeindex/
├── models.py         # NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums NodeKind/EdgeKind
├── graph_store.py    # GraphStore: SQLite + NetworkX cache en memoria
├── indexer.py        # Orquestador: recorre archivos, detecta cambios por SHA-256, parsea
├── metrics.py        # [Fase 1] Ca, Ce, inestabilidad, ciclos, god modules — TODO
├── cli.py            # CLI: index, search, summary, impact, imports, status, callers, metrics, baseline
├── logging.py        # Configuración structlog (dev vs prod)
├── embedder.py       # [CONGELADO] Embeddings semánticos — no desarrollar más
└── parser/
    ├── base.py           # LanguageParser (abstracta)
    ├── python_parser.py  # Tree-sitter Python
    └── js_parser.py      # Tree-sitter JS/TS
```

### Flujo de datos

```
Archivo fuente → Parser (Tree-sitter) → (NodeInfo[], EdgeInfo[]) → GraphStore.store_file()
                                                                    ├── SQLite (persistencia)
                                                                    └── NetworkX DiGraph (cache, invalidable)
```

---

## Schema SQLite

Tres tablas: `nodes`, `edges`, `metadata`.

- **nodes**: `id`, `kind` (File/Class/Function/Method), `name`, `qualified_name` (UNIQUE), `file_path`, `line_start`, `line_end`, `language`, `parent_name`, `signature`, `docstring`, `decorators` (JSON), `file_hash`, `extra` (JSON), `updated_at`
- **edges**: `id`, `kind` (CONTAINS/HAS_METHOD/IMPORTS_FROM/INHERITS/CALLS/COVERS/USES_TYPE), `source_qualified`, `target_qualified`, `file_path`, `line`, `extra` (JSON), `updated_at`
- **metadata**: `key`, `value` — almacenamiento genérico clave-valor

### Persistencia del baseline

`.codeindex/baseline.json` — snapshot de métricas de acoplamiento (Ca, Ce, ciclos, god modules) guardado con `codeindex baseline save`. Se commitea al repo; es la referencia para el ratcheting en CI. El `.codeindex/.gitignore` es gestionado por codeIndex y siempre se sobreescribe: ignora todo excepto `.gitignore` y `baseline.json`.

### qualified_name

Identificador único de cualquier símbolo:
```
src/auth/service.py                        # File
src/auth/service.py::AuthService           # Class
src/auth/service.py::AuthService.validate  # Method
src/auth/service.py::create_app            # Function
```

### Escritura atómica

Cuando un archivo cambia: `BEGIN IMMEDIATE` → delete todos sus nodos/aristas → insert nuevos → commit. Si falla, nada cambia.

---

## Code style

- **ruff** con `line-length=100`, `target-version="py310"`, reglas `E,F,W,I,B,C4,UP`
- **Google style docstrings** en todas las funciones y clases públicas
- **Type hints** obligatorios en todos los parámetros y retornos
- Imports ordenados por ruff (isort integrado)

---

## Logging (structlog)

```python
import structlog
log = structlog.get_logger()
log = log.bind(file_path="src/app.py", operation="index")
log.info("indexing_started")
log.warning("parse_warning", reason="no docstring")
log.error("index_failed", exc_info=True)
```

- `CODEINDEX_LOG_JSON=false` → consola coloreada (dev, por defecto)
- `CODEINDEX_LOG_JSON=true` → JSON lines (prod/observabilidad)
- Los logs van **siempre** a `.codeindex/codeindex.log`, nunca a stdout

---

## Commits — Conventional Commits (commitizen)

Formato: `<type>(<scope>): <description>`

Tipos válidos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

Ejemplos:
```
feat(parser): add CALLS edge extraction for Python
fix(store): handle duplicate qualified_name on re-index
test(indexer): add fixture for JS files
```

---

## TDD — obligatorio

- Escribir el test **antes** que la implementación (Red → Green → Refactor)
- Los tests son la especificación ejecutable del comportamiento esperado
- Coverage configurado: `--cov=codeindex --cov-report=term-missing`

---

## CI

| Evento | Checks obligatorios |
|--------|---------------------|
| `commit` | ruff + commitizen |
| `push` | pytest (todos los tests) |
| `pull_request` | pytest + ruff + bandit |

Pre-commit hooks: ruff (lint + format), commitizen, bandit.

---

## Principios de diseño

- **SOLID, KISS, YAGNI** — la solución más simple que funciona
- **Decoupled**: parsers, store y CLI son intercambiables sin dependencias circulares
- **NetworkX como cache**: SQLite persiste, NetworkX computa traversals (BFS, impacto, dependencias transitivas). Cache se invalida tras cada escritura.
- **Batch queries**: lotes de 450 para no superar el límite de variables SQLite (999)

---

## Lenguajes soportados

| Lenguaje | Extensiones |
|----------|-------------|
| Python | `.py` |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` |

Directorios ignorados en indexación: `.git`, `__pycache__`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `.idea`, `.vscode`.

---

## Fixture de test de referencia

`tests/fixtures/sample.py` — servicio Flask de ejemplo. Al parsearse debe producir:
- **Nodos**: 1 File + 3 Class (`User`, `UserService`, `AdminService`) + 5 Method + 2 Function = **11 nodos**
- **Aristas**: CONTAINS × 3 + HAS_METHOD × 5 + IMPORTS_FROM × 4 + INHERITS × 1 = **~14 aristas**

Usar como smoke test tras tocar parsers o GraphStore.

---

## Referencia de diseño

Patrones adoptados de [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph):
`qualified_name` como ID único · escritura atómica por archivo · NetworkX como cache · batch queries de 450 · BFS bidireccional para impacto · tabla `metadata` key-value · sanitización de nombres contra prompt injection.

---

## Roadmap

Ver [`TODO.md`](TODO.md) para la lista completa y priorizada de tareas pendientes.
