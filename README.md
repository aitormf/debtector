# CodeIndex

Grafo de código sobre SQLite que extrae la estructura de un repositorio (clases, funciones, métodos, imports, llamadas) y la almacena como un grafo consulable. Diseñado para reducir el consumo de tokens de IA: en lugar de leer ficheros fuente completos, el modelo consulta el grafo.

```
codeindex --json search "AuthService"
codeindex --json impact src/auth.py --depth 3
codeindex --json callers "src/auth.py::AuthService.validate"
```

## Instalación

```bash
pip install codeindex
# o con uv
uv add codeindex
```

**Requisitos:** Python ≥ 3.10

## Inicio rápido

```bash
# 1. Indexar el proyecto (incremental: solo reparsea ficheros cambiados)
codeindex index ./src

# 2. Consultar el estado del grafo
codeindex status

# 3. Buscar un símbolo
codeindex search "UserService"

# 4. Ver todos los símbolos de un fichero
codeindex summary src/auth/service.py

# 5. Saber qué ficheros se ven afectados si cambias uno
codeindex impact src/auth/service.py --depth 3
```

El índice se guarda en `.codeindex/index.db` (SQLite). Los logs van a `.codeindex/codeindex.log`.

## Comandos

| Comando | Descripción |
|---------|-------------|
| `index <dir>` | Indexa el directorio (incremental por hash SHA-256) |
| `status` | Estadísticas del grafo (ficheros, nodos, aristas por tipo) |
| `search <query>` | Busca símbolos por nombre. `--kind Class\|Function\|Method` para filtrar |
| `summary <file>` | Todos los símbolos e imports de un fichero |
| `impact <files...>` | Qué ficheros y nodos se ven afectados por un cambio. `--depth N` |
| `imports <module>` | Qué ficheros importan un módulo o librería |
| `callers <qname>` | Qué funciones/métodos llaman a un símbolo concreto |
| `install-skill` | Instala los skills de Claude Code (ver más abajo) |
| `install-hook` | Instala un hook git pre-commit para auto-indexado |

### Flag global `--json`

Todos los comandos admiten `--json` para emitir JSON compacto en stdout, pensado para consumo por IA:

```bash
codeindex --json search "GraphStore"
codeindex --json impact src/models.py --depth 2
codeindex --json status
```

### `--project`

Por defecto el índice vive en `./.codeindex/`. Usa `--project /ruta/repo` para apuntar a otro directorio:

```bash
codeindex --project /otro/repo index /otro/repo/src
codeindex --project /otro/repo --json search "Service"
```

## Lenguajes soportados

| Lenguaje | Extensiones |
|----------|------------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |

## Grafo generado

### Tipos de nodos

| Tipo | Descripción |
|------|-------------|
| `File` | Fichero fuente |
| `Class` | Clase |
| `Function` | Función top-level o arrow function |
| `Method` | Método de clase |

### Tipos de aristas

| Tipo | Descripción |
|------|-------------|
| `CONTAINS` | Fichero → clase/función |
| `HAS_METHOD` | Clase → método |
| `IMPORTS_FROM` | Fichero → módulo importado |
| `INHERITS` | Clase → clase base |
| `CALLS` | Función/método → función/método llamado (resolución intra-fichero) |

### Qualified names

Cada símbolo tiene un `qualified_name` único:

```
src/auth/service.py                        # fichero
src/auth/service.py::AuthService           # clase
src/auth/service.py::AuthService.validate  # método
src/auth/service.py::create_app            # función
```

## Auto-indexado con git hook

Instala un hook pre-commit que re-indexa automáticamente antes de cada commit:

```bash
codeindex install-hook
```

El hook es incremental (solo reparsea ficheros con hash distinto), silencioso, y nunca bloquea un commit. Si quieres incluir el índice en cada commit:

```bash
codeindex install-hook --add-to-stage
```

## Integración con Claude Code (skills)

Instala los skills para que Claude Code sepa cómo usar CodeIndex:

```bash
# Global (todos los proyectos)
codeindex install-skill --global

# Solo este proyecto
codeindex install-skill
```

Esto copia dos skills a `.claude/skills/` (o `~/.claude/skills/` con `--global`):

- **`codeindex`** — referencia completa de comandos y flujos típicos
- **`codeindex-bootstrap`** — guía de primera configuración en un repo nuevo

Con los skills instalados, Claude Code reconoce frases como *"analiza el impacto de cambiar AuthService"* o *"¿quién importa flask?"* y llama automáticamente al CLI con `--json`.

## Directorio `.codeindex/`

```
.codeindex/
  index.db        # grafo SQLite (commiteable si quieres compartirlo)
  codeindex.log   # logs estructurados (ignorado por git)
  .gitignore      # generado automáticamente: ignora todo excepto *.db y .gitignore
```

## Desarrollo

```bash
# Clonar e instalar dependencias
git clone https://github.com/aitormf/codeIndex
cd codeIndex
uv sync --extra dev

# Tests
uv run pytest

# Linter + formatter
uv run ruff check .
uv run ruff format .

# Seguridad
uv run bandit -r src/

# Instalar pre-commit hooks
uv run pre-commit install                          # stage pre-commit
uv run pre-commit install --hook-type commit-msg   # stage commit-msg
uv run pre-commit install --hook-type pre-push     # stage pre-push
```

Los tres comandos son necesarios porque el proyecto tiene hooks en tres stages distintos:

| Stage | Hooks |
|---|---|
| `pre-commit` | ruff, ruff-format, bandit, trailing-whitespace… |
| `commit-msg` | commitizen (formato Conventional Commits), bloqueo de atribuciones a IA |
| `pre-push` | pytest, ruff-check |

> **Nota:** `pre-commit install` solo instala el stage `pre-commit`. Sin los otros dos comandos los hooks de `commit-msg` y `pre-push` no se ejecutan aunque estén definidos en `.pre-commit-config.yaml`.

## Logging

```bash
# Logs en formato legible (por defecto)
CODEINDEX_LOG_JSON=false codeindex index ./src

# Logs en JSON (para sistemas de observabilidad)
CODEINDEX_LOG_JSON=true codeindex index ./src
```

Los logs siempre van a `.codeindex/codeindex.log`, nunca a stdout.

## Roadmap

- [x] FTS5 — búsqueda léxica/ranked sin deps adicionales
- [ ] Búsqueda semántica — `sqlite-vec` + `fastembed` (ver [ADR-001](docs/decisions/001-semantic-search.md))
- [ ] Exportación del grafo — DOT/JSON para visualización
- [ ] Más lenguajes — Go, Rust, Java
- [ ] Schema migrations — versionado del esquema SQLite
- [ ] Ignorar rutas — soporte para `.codeindexignore`

## Licencia

MIT
