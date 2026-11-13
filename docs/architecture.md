# Debtector Architecture

[Leer en Español](architecture.es.md)

## Overview

Debtector analyzes source code repositories, extracts their structure (classes, functions, methods, imports, calls) and stores it as a **graph in SQLite**. The goal is to **detect code coupling in CI pipelines and PR reviews**, giving developers architectural context before merging.

ICP: developer or tech lead using code agents (Claude Code, Copilot, Codex). Agents generate hidden coupling faster than any human can track; Debtector acts as an architectural guardrail in the pipeline.

See [D-0002](decisions/0002-pivot-ci-coupling.md) for the full context of the pivot.

---

## Modules

```
src/debtector/
├── models.py         # Data types: NodeInfo, EdgeInfo, GraphNode, GraphEdge, enums
├── graph_store.py    # Persistence: SQLite + FTS5 + in-memory NetworkX cache; test classification
├── indexer.py        # Orchestration: walks files, detects changes, calls parsers
├── metrics.py        # Ca, Ce, instability, cycles, god modules, SDP, inheritance
├── git_history.py    # Behavioral analysis: churn, hotspots, temporal coupling, bus factor
├── diff.py           # Architectural diff between two indexes (base vs. PR)
├── config.py         # Loads and validates debtector.toml (thresholds and severity)
├── utils.py          # Shared utilities: is_test_file()
├── logging.py        # structlog configuration (colored dev / JSON prod)
├── cli/              # CLI package, one module per command group (D-0011)
│   ├── app.py            # argparse and dispatch
│   ├── common.py         # shared helpers (store, index root, test paths, output)
│   ├── graph.py          # index, search, summary, impact, imports, status, callers
│   ├── coupling.py       # coupling (and the deprecated metrics alias)
│   ├── baseline.py       # baseline save / status
│   ├── reporters.py      # GitHub annotations and GitLab report
│   ├── quality.py        # complexity, untested, audit
│   ├── git.py            # hotspots, temporal-coupling, bus-factor, git-coupling
│   ├── report.py         # report
│   └── pr_diff.py        # diff
├── audit/            # Audit surface (D-0003): health score, LCOM4, testRisk, cycle priority, complexity
├── render/
│   └── diff_markdown.py  # Markdown of the diff for the PR comment
└── parser/
    ├── base.py           # LanguageParser — abstract class
    ├── complexity.py     # Cyclomatic complexity (McCabe) on tree-sitter trees (D-0004)
    ├── python_parser.py  # PythonParser — Tree-sitter Python
    └── js_parser.py      # JavaScriptParser — Tree-sitter JS/TS
```

### Responsibilities

| Module | Responsibility |
|---|---|
| `models.py` | Defines input types (`NodeInfo`, `EdgeInfo`) and output types (`GraphNode`, `GraphEdge`) with no internal dependencies |
| `graph_store.py` | Single source of truth. Writes to SQLite, maintains a NetworkX DiGraph as cache for traversals |
| `indexer.py` | Walks the filesystem, detects changes by SHA-256, delegates parsing and calls `GraphStore.store_file()`. Generates COVERS edges after each indexing run (non-fatal) |
| `metrics.py` | Computes **structural** coupling metrics on the graph: Ca, Ce, instability, cycles (Tarjan), god modules (p90), SDP violations, inheritance depth |
| `git_history.py` | Computes **behavioral** coupling metrics on git history: churn (`git log --numstat`), hotspot score, temporal coupling, bus factor (`git blame`). Read-only; does not write to DB |
| `diff.py` | Compares two indexes with the rules of `baseline status` (D-0008) and decides whether the result blocks CI (`blocks_ci`). Schema in [diff-schema.md](diff-schema.md) |
| `audit/` | Second presenter over the same graph (D-0003): health score, LCOM4, testRisk, cycle priority, function complexity. Schema in [audit-schema.md](audit-schema.md) |
| `config.py` | Reads `debtector.toml` with `tomllib` (stdlib). Exposes `DebtectorConfig` with configurable thresholds and severities |
| `utils.py` | Shared utilities with no internal dependencies: `is_test_file()` |
| `parser/*` | Transform a source file into `(list[NodeInfo], list[EdgeInfo])` using Tree-sitter. No DB access |
| `cli/` | Translates command-line arguments into calls to GraphStore, metrics and git_history. No business logic of its own. Silently auto-indexes before each analysis command |

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
    │     ├── hotspots        → churn × cyclomatic complexity
    │     ├── temporal coupl. → git log --name-only, co-changing pairs
    │     └── bus factor      → git blame --line-porcelain
    ├── Full report          → coupling + git-coupling   (debtector report)
    ├── Audit                → audit/ + metrics + git    (debtector audit)
    ├── Baseline / ratcheting → baseline.json + delta    (debtector baseline)
    └── PR diff              → diff.py, base ref indexed in a temporary worktree (debtector diff)
```

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
    node_id UNINDEXED,
    name, qualified_name, signature, docstring,
    tokenize = 'unicode61'
);
```

BM25 ranking with camelCase splitting: `"UserService"` → tokens `user`, `service`, `userservice`. Each term is expanded with `*` for prefix matching.

---

## Baseline persistence

`.debtector/baseline.json` — coupling metrics snapshot generated with `debtector baseline save`. Committed to the repo; it is the shared reference for ratcheting in CI.

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

`metrics_version` is the version of the coupling metrics (D-0014): a baseline saved with another version does not compare god modules, SDP or instability. `complexity` keeps the functions at or above `complexity_medium` (D-0019).

The `.debtector/.gitignore` is managed by Debtector (always overwritten): ignores everything except `baseline.json` and the `.gitignore` itself.

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
| `USES_TYPE` | Function references a type in its type hints (not counted in Ca/Ce, D-0012) | `app.py::get_user` → `User` |
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
| Fan-in (Ca) | Number of distinct internal modules that import this one | ≥ 0 |
| Fan-out (Ce) | Number of distinct internal modules this one imports | ≥ 0 |
| Instability (I) | Ce / (Ca + Ce) | [0, 1] |

A module is flagged **unstable** only if it is the target of a Stable Dependencies Principle violation: an `IMPORTS_FROM` edge `A → B` between indexed modules with `I(B) > I(A) + sdp_margin`. High I on a leaf is normal and is not flagged. A **god module** needs Ca above the `god_module_percentile` **and** `Ca >= god_module_min_ca`.

Only `IMPORTS_FROM` edges that resolve to a file in the index count (D-0012): standard-library and third-party imports, repeated imports of the same module and `USES_TYPE` edges do not. Python absolute imports are resolved from the package root (D-0016) and `from X import a` depends on the submodule `X.a` when it exists (D-0018). Test files are neither modules nor dependents (D-0015). Pure package facades (`__init__.py` or JS/TS `index.*` with no classes or functions) take no part in SDP violations (D-0017).

### Cycles

Detection via the **iterative Tarjan algorithm** (avoids RecursionError on long chains) over `IMPORTS_FROM` and `CALLS` edges. Returns SCCs with size > 1.

### God modules

Statistical outlier in Ca: modules whose fan-in exceeds the **90th percentile** of the project **and** reaches `god_module_min_ca` (10). Both configurable in `debtector.toml`.

### Inheritance

Depth (longest path from root) and number of direct children, traversing `INHERITS` edges. Supports cross-file inheritance; cuts cycles.

---

## Behavioral metrics (Phase 2)

### Churn

Number of distinct commits touching each file, computed with `git log --numstat`. Binary files are counted but their line counts are recorded as 0. Accepts a `--since` filter (e.g. `"6 months ago"`).

### Hotspot score

`churn × complexity` — combines historical activity with code complexity (the sum of the cyclomatic complexity of the file's functions and methods, computed at index time). A heavily changed and complex file is the highest technical debt risk point; files without functions score 0. Structural coupling (`fan_in + fan_out`) is reported alongside but does not take part in the score. Sorted descending.

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
god_module_min_ca     = 10    # absolute minimum Ca for a god module (default: 10)
sdp_margin            = 0.1   # min I(B) - I(A) to flag A -> B as SDP violation (default: 0.1)
# instability_threshold: deprecated, ignored (warning logged)
max_inheritance_depth = 5     # maximum inheritance depth (default: 5)
max_children          = 10    # maximum direct children (default: 10)

[metrics.severity]
cycles      = "error"    # error | warning | info (default: error)
god_modules = "warning"  # (default: warning)
instability = "warning"  # (default: warning)
inheritance = "info"     # (default: info)
complexity  = "warning"  # worsened functions in diff / baseline status (default: warning)
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
- **Instability regression** > `INSTABILITY_TOLERANCE` (0.05, in `diff.py`) → according to `severity.instability`
- **New SDP violations** (`A → B` with `I(B) > I(A) + sdp_margin`) → according to `severity.instability`. Only compared when the baseline contains `sdp_violations`; older baselines are not flagged
- **New or worsened functions** with complexity >= `complexity_medium` → according to `severity.complexity`. Skipped (`complexity_skipped`) when the baseline has no `complexity` or was saved with another `complexity_medium`
- **Baseline from another `metrics_version`** → god modules, SDP and instability are not compared (cycles are)
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

## Architecture decisions

| ADR | Decision |
|---|---|
| [D-0001](decisions/0001-semantic-search.md) | FTS5 + sqlite-vec + fastembed for semantic search (implemented, frozen, then removed; FTS5 remains) |
| [D-0002](decisions/0002-pivot-ci-coupling.md) | Pivot: from AI navigation to coupling analysis for CI/PR |

The full, up-to-date list is in [decisions/README.md](decisions/README.md).
