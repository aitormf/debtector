# Debtector Architecture

[Leer en Español](architecture.es.md)

## Overview

Debtector analyzes source code repositories, extracts their structure (classes, functions, methods, imports, calls) and stores it as a **graph in SQLite**. The goal is to **detect code coupling in CI pipelines and PR reviews**, giving developers architectural context before merging.

ICP: developer or tech lead using code agents (Claude Code, Copilot, Codex). Agents generate hidden coupling faster than any human can track; codeIndex acts as an architectural guardrail in the pipeline.

See [ADR-002](decisions/002-pivot-ci-coupling.md) for the full context of the pivot.

---

## Modules

```
src/debtector/
├── models.py         # Data types: NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
├── graph_store.py    # Persistence: SQLite + in-memory NetworkX cache
├── indexer.py        # Orchestration: walks files, detects changes, calls parsers
├── metrics.py        # Ca, Ce, instability, cycles, god modules, inheritance
├── git_history.py    # Behavioral analysis: churn, hotspots, temporal coupling, bus factor
├── config.py         # Loads and validates debtector.toml (thresholds and severity)
├── cli.py            # CLI: index, search, summary, impact, imports, callers,
│                     #       untested, status, coupling, baseline,
│                     #       hotspots, temporal-coupling, bus-factor, git-coupling, report
├── utils.py          # Shared utilities: is_test_file()
├── logging.py        # structlog configuration (colored dev / JSON prod)
├── embedder.py       # [FROZEN] Semantic embeddings — do not develop further
│                     #   Available with uv add 'debtector[semantic]'
└── parser/
    ├── base.py           # LanguageParser — abstract class
    ├── python_parser.py  # PythonParser — Tree-sitter Python
    └── js_parser.py      # JavaScriptParser — Tree-sitter JS/TS
```

### Responsibilities

| Module | Responsibility |
|---|---|
| `models.py` | Defines input types (`NodeInfo`, `EdgeInfo`) and output types (`GraphNode`, `GraphEdge`) with no internal dependencies |
| `graph_store.py` | Single source of truth. Writes to SQLite, maintains a NetworkX DiGraph as cache for traversals |
| `indexer.py` | Walks the filesystem, detects changes by SHA-256, delegates parsing and calls `GraphStore.store_file()`. Generates COVERS edges after each indexing run (non-fatal) |
| `metrics.py` | Computes **structural** coupling metrics on the graph: Ca, Ce, instability, cycles (Tarjan), god modules (p90), inheritance depth |
| `git_history.py` | Computes **behavioral** coupling metrics on git history: churn (`git log --numstat`), hotspot score, temporal coupling, bus factor (`git blame`). Read-only; does not write to DB |
| `config.py` | Reads `debtector.toml` with `tomllib` (stdlib). Exposes `DebtectorConfig` with configurable thresholds and severities |
| `embedder.py` | **[Frozen]** Converts nodes to text and generates float32 vectors with fastembed. Do not develop further |
| `utils.py` | Shared utilities with no internal dependencies: `is_test_file()` |
| `parser/*` | Transform a source file into `(list[NodeInfo], list[EdgeInfo])` using Tree-sitter. No DB access |
| `cli.py` | Translates command-line arguments into calls to GraphStore, metrics and git_history. No business logic of its own. Silently auto-indexes before each analysis command |

---

## Data flow

### Indexing

```
Source file
    │
    ▼
Indexer — detects change by SHA-256
    │
    ▼
Parser (Tree-sitter) ──→ (list[NodeInfo], list[EdgeInfo])
    │                         incl. USES_TYPE from type hints
    ▼
GraphStore.store_file()
    ├── SQLite  (persistence)
    └── NetworkX DiGraph  (invalidatable cache for traversals)
```

### Query and analysis

```
CLI / CI pipeline
    │
    ├── Silent auto-index → Indexer (SHA-256, no-op if no changes)
    │
    ├── Lexical search       → SQLite FTS5              (debtector search)
    ├── Direct lookup        → SQLite SQL                (summary, callers, imports)
    ├── Impact traversal     → NetworkX                  (debtector impact)
    ├── Structural coupling  → metrics.py + graph        (debtector coupling)
    ├── Behavioral coupling  → git_history.py + git      (debtector git-coupling)
    │     ├── churn           → git log --numstat
    │     ├── hotspots        → churn × (fan_in + fan_out)
    │     ├── temporal coupl. → git log --name-only, co-changing pairs
    │     └── bus factor      → git blame --line-porcelain
    ├── Full report          → coupling + git-coupling   (debtector report)
    └── Baseline / ratcheting → baseline.json + delta    (debtector baseline)
```

> Semantic search (`sqlite-vec` KNN) is frozen. See [Frozen semantics](#frozen-semantics).

---

## SQLite schema

The index lives in `.debtector/index.db`. Three relational tables:

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
    parent_name     TEXT,                  -- "UserService" (methods only)
    signature       TEXT,                  -- "def get_user(self, id: int) -> User"
    docstring       TEXT,
    decorators      TEXT DEFAULT '[]',     -- JSON array
    file_hash       TEXT DEFAULT '',       -- SHA-256 of the source file
    extra           TEXT DEFAULT '{}',     -- free JSON for future extensions
    updated_at      REAL NOT NULL
);

CREATE TABLE edges (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    kind              TEXT NOT NULL,       -- see EdgeKind below
    source_qualified  TEXT NOT NULL,       -- qualified_name of the source
    target_qualified  TEXT NOT NULL,       -- qualified_name of the target
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

### Indexes

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

BM25 ranking with camelCase splitting: `"UserService"` → tokens `user`, `service`, `userservice`. Each term is expanded with `*` for prefix matching.

---

## Baseline persistence

`.debtector/baseline.json` — coupling metrics snapshot generated with `debtector baseline save`. Committed to the repo; it is the shared reference for ratcheting in CI.

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

The `.debtector/.gitignore` is managed by codeIndex (always overwritten): ignores everything except `baseline.json` and the `.gitignore` itself.

---

## Node and edge types

### NodeKind

| Value | Description |
|---|---|
| `File` | An indexed source file |
| `Class` | Class definition |
| `Function` | Top-level function |
| `Method` | Method within a class |

### EdgeKind

| Value | Meaning | Example |
|---|---|---|
| `CONTAINS` | File contains top-level symbol | `app.py` → `app.py::UserService` |
| `HAS_METHOD` | Class has method | `app.py::UserService` → `app.py::UserService.get_user` |
| `IMPORTS_FROM` | File imports module or symbol | `app.py` → `flask` |
| `INHERITS` | Class inherits from another | `app.py::AdminService` → `UserService` |
| `CALLS` | Function/method calls another symbol | `app.py::create_app` → `app.py::UserService.__init__` |
| `COVERS` | Test exercises a production symbol | `tests/test_auth.py::test_login` → `src/auth.py::login` |
| `USES_TYPE` | Function references a type in its type hints (weight 1.0 in Ca/Ce) | `app.py::get_user` → `User` |
| `DEPENDS_ON` | Generic dependency (future use) | — |

---

## qualified_name

Unique identifier for any symbol in the entire codebase:

```
src/auth/service.py                        → File
src/auth/service.py::AuthService           → Class
src/auth/service.py::AuthService.validate  → Method
src/auth/service.py::create_app            → Function
```

---

## Coupling metrics (Phase 1)

### Fan-in / Fan-out / Instability

| Metric | Definition | Range |
|---|---|---|
| Fan-in (Ca) | Weighted sum of incoming IMPORTS_FROM + USES_TYPE edges | ≥ 0 |
| Fan-out (Ce) | Weighted sum of outgoing IMPORTS_FROM + USES_TYPE edges | ≥ 0 |
| Instability (I) | Ce / (Ca + Ce) | [0, 1] |

Weights: `IMPORTS_FROM` = 1.0, `USES_TYPE` = 1.0. Both weights are public constants in `metrics.py` (`IMPORTS_FROM_WEIGHT`, `USES_TYPE_WEIGHT`) to facilitate adjustments in experiments.

### Cycles

Detection via the **iterative Tarjan algorithm** (avoids RecursionError on long chains) over `IMPORTS_FROM` and `CALLS` edges. Returns SCCs with size > 1.

### God modules

Statistical outlier in Ca: modules whose fan-in exceeds the **90th percentile** of the project (relative threshold, not absolute). Configurable in `debtector.toml`.

### Inheritance

Depth (longest path from root) and number of direct children, traversing `INHERITS` edges. Supports cross-file inheritance; cuts cycles.

---

## Behavioral metrics (Phase 2)

### Churn

Number of distinct commits touching each file, computed with `git log --numstat`. Binary files are counted but their line counts are recorded as 0. Accepts a `--since` filter (e.g. `"6 months ago"`).

### Hotspot score

`churn × (fan_in + fan_out)` — combines historical activity with structural coupling. A heavily changed and heavily coupled file is the highest technical debt risk point. Sorted descending.

### Temporal coupling

File pairs that appear together in commits more frequently than a threshold. Detects implicit dependencies not visible in the import graph. Parameters:
- `min_shared` (default: 5): minimum shared commits
- `min_ratio` (default: 0.3): minimum `shared / min(commits_a, commits_b)`

### Bus factor

Minimum number of authors needed to cover 80% of the active lines in a file, computed with `git blame --line-porcelain`. A bus factor of 1 indicates a single point of knowledge failure. Only processes files present in the index.

---

## Configuration (`debtector.toml`)

Optional file at the project root. Uses `tomllib` from the stdlib (Python 3.12+):

```toml
[metrics.thresholds]
god_module_percentile = 90    # Ca percentile for god module (default: 90)
instability_threshold = 0.8   # I >= threshold → warning (default: 0.8)
max_inheritance_depth = 5     # maximum inheritance depth (default: 5)
max_children          = 10    # maximum direct children (default: 10)

[metrics.severity]
cycles      = "error"    # error | warning | info (default: error)
god_modules = "warning"  # (default: warning)
instability = "warning"  # (default: warning)
inheritance = "info"     # (default: info)
```

**Severities:**
- `error` → exit code 1, blocks CI
- `warning` → reports but exit code 0
- `info` → silent, exit code 0

---

## Ratcheting CI

`debtector baseline status` compares the current state against the saved baseline:

- **New cycles** not present in baseline → according to `severity.cycles`
- **New god modules** → according to `severity.god_modules`
- **Instability regression** > `_INSTABILITY_TOLERANCE` (0.05) → according to `severity.instability`
- **No baseline** → always exit code 0 (silent mode)

### CI reporter

`--reporter github` emits GitHub Actions Annotations:
```
::error file=src/auth.py,line=1::Import cycle: src/auth.py → src/user.py
```

`--reporter gitlab` emits GitLab CI section markers with ANSI.

---

## Key implementation patterns

### Atomic write per file

When a file changes, all its nodes and edges are replaced within a single transaction:

```
BEGIN IMMEDIATE
  DELETE FROM nodes WHERE file_path = ?
  DELETE FROM edges WHERE file_path = ?
  INSERT INTO nodes ...
  INSERT INTO edges ...
COMMIT
```

If anything fails, nothing changes. This simplifies incremental indexing: no partial merges.

### NetworkX as traversal cache

SQLite persists the data. For complex graph queries (impact BFS, transitive dependency chains) everything is loaded into an in-memory NetworkX `DiGraph`. The cache is automatically invalidated after each write.

### Batch queries of 450

SQLite has a limit of 999 variables per query. Queries with `IN (...)` are split into batches of 450 to stay well within that limit.

### Change detection by SHA-256

The Indexer compares the SHA-256 hash of the file on disk with the one stored in `nodes.file_hash`. Only re-parses files that have changed.

### USES_TYPE dedup in O(1)

The type hint extractor maintains a `set[str]` shared per file (`uses_type_seen`) that is threaded through the entire `_extract_symbols` recursion. Avoids an O(F×E) scan of the edge list for each function.

---

## Frozen semantics

`embedder.py`, `sqlite-vec` and `fastembed` are frozen: the code exists but will not be developed further. They are not part of the CI/PR objective.

- Available as an optional dependency: `uv add 'debtector[semantic]'`
- The `debtector semantic` command returns an error with a deprecation message
- Embedding tests still exist but do not cover the current objective

See [ADR-002](decisions/002-pivot-ci-coupling.md) for the full reasoning.

---

## Parsers

Each parser implements `LanguageParser` (abstract in `parser/base.py`) and receives a file path, returning `(list[NodeInfo], list[EdgeInfo])`.

### What each parser extracts

- `File` node for the file itself
- `Class`, `Function`, `Method` nodes for each symbol
- `CONTAINS`, `HAS_METHOD`, `IMPORTS_FROM`, `INHERITS`, `CALLS` edges
- `USES_TYPE` edges from type hints in signatures (uppercase-initial names only)
- `signature` and `docstring` when available

### Supported languages

| Language | Extensions | Parser |
|---|---|---|
| Python | `.py` | `PythonParser` (Tree-sitter) |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | `JavaScriptParser` (Tree-sitter) |

---

## Directories ignored during indexing

`.git`, `__pycache__`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `.idea`, `.vscode`

Additional support for `.debtectorignore` (gitignore-style).

---

## Architecture decisions

| ADR | Decision |
|---|---|
| [001](decisions/001-semantic-search.md) | FTS5 + sqlite-vec + fastembed for semantic search (implemented, then frozen) |
| [002](decisions/002-pivot-ci-coupling.md) | Pivot: from AI navigation to coupling analysis for CI/PR |
