---
name: codeindex
description: Query the CodeIndex code structure graph to find symbols, analyse impact, trace imports and callers, and summarise files — without reading source files directly.
triggers:
  - codeindex
  - code structure
  - impact analysis
  - find callers
  - search symbols
  - who imports
  - blast radius
  - dependency graph
  - where is defined
  - find definition
  - class hierarchy
  - inheritance graph
  - trace dependency
  - refactor impact
---

# CodeIndex — Code Graph Query Tool

CodeIndex maintains a structural graph of the codebase stored in `.codeindex/index.db`.
Use `codeindex --json <subcommand>` to query it. All output is compact JSON — parse it directly, do not re-read source files for information already in the index.

## When to use each subcommand

| Goal | Command |
|------|---------|
| Find a class, function or method by name | `search` |
| See all symbols and imports in one file | `summary` |
| Know which files are affected by a change | `impact` |
| Find who imports a library or module | `imports` |
| Find who calls a specific function/method | `callers` |
| Get overall stats (node/edge counts) | `status` |
| Refresh the index after editing files | `index` |
| Install skill files into Claude Code | `install-skill` |
| Set up git pre-commit auto-indexing | `install-hook` |

## Command reference

### status — index health check
```bash
codeindex --json status
```
Returns: `{"files": N, "total_nodes": N, "total_edges": N, "languages": [...], "nodes_by_kind": {...}, "edges_by_kind": {...}}`

Run this first to confirm the index exists and is non-empty.

---

### search — find symbols by name (FTS5 + BM25)
```bash
codeindex --json search "<query>"
codeindex --json search "<query>" --kind Class   # or Function, Method
```
Returns: array of `{kind, name, qualified_name, file_path, line_start, line_end, signature}`

Search uses **FTS5 full-text search with BM25 ranking**. Key behaviours:
- **camelCase splitting**: `"UserService"` matches `user`, `service`, and `userservice`
- **Prefix matching**: each word is automatically expanded with `*` (e.g. `auth` also matches `authenticate`)
- **Multi-word**: `"parse token"` finds nodes that contain both terms (order-independent)
- **Kind filter**: `--kind Class|Function|Method` narrows results
- Falls back to SQL `LIKE` if the FTS5 table is missing

Use `qualified_name` as the stable identifier for any follow-up queries.

---

### summary — all symbols in a file
```bash
codeindex --json summary <relative/path/to/file.py>
```
Returns: `{path, language, nodes: [...], edges: [...]}`

Each node has `{kind, name, parent, signature}`. Each edge has `{kind, source, target}`.

---

### impact — blast radius of a change
```bash
codeindex --json impact <file1> [file2 ...] --depth 3
```
Returns: `{changed_nodes: [...qnames], impacted_nodes: [...], impacted_files: [...]}`

Default depth is 2. Increase to 3–4 for deep dependency chains. Use before any refactor that touches public APIs.

---

### imports — who uses a module/library
```bash
codeindex --json imports <module_name>
```
Returns: array of `{file_path, line, source, target}`

Works on any substring of the import target (e.g. `"flask"`, `"structlog"`, `".database"`).

---

### callers — who calls a function or method
```bash
codeindex --json callers "<qualified_name>"
```
Returns: array of node dicts for callers.

The `qualified_name` format is `path/to/file.py::ClassName.method_name` or `path/to/file.py::function_name`.

CALLS edges are extracted by the Python and JS/TS parsers and stored in the index.

---

### index — refresh the index
```bash
codeindex index <directory>
codeindex --json index <directory>
```
Run after editing files. Incremental — only re-parses changed files (based on SHA-256 hash). JSON returns `{scanned, indexed, skipped, errors, removed}`.

---

### install-skill — copy skills into Claude Code
```bash
codeindex install-skill              # project-level: .claude/skills/
codeindex install-skill --global     # user-level: ~/.claude/skills/
```
Copies `codeindex.md` and `codeindex-bootstrap.md` to the appropriate skills directory so Claude Code can trigger them automatically.

---

### install-hook — git pre-commit auto-indexing
```bash
codeindex install-hook                   # silent: re-indexes on every commit
codeindex install-hook --add-to-stage    # also stages .codeindex/index.db
```
Appends a shell snippet to `.git/hooks/pre-commit` (idempotent). The hook runs `codeindex index .` before every commit so the index is never stale. With `--add-to-stage`, the updated `index.db` is included in the commit automatically.

---

## Typical workflows

**Before refactoring a public function:**
```bash
codeindex --json search "my_function" --kind Function
codeindex --json impact path/to/file.py --depth 3
codeindex --json callers "path/to/file.py::my_function"
```

**Understanding a new file:**
```bash
codeindex --json summary path/to/file.py
```

**Checking library adoption:**
```bash
codeindex --json imports flask
codeindex --json imports ".database"   # relative imports
```

**After editing files:**
```bash
codeindex index .
codeindex --json status
```

**First-time project setup:**
```bash
codeindex index .
codeindex install-skill          # make skills available in Claude Code
codeindex install-hook           # auto-index on every git commit
```

## Project path

By default `--project` is `.` (current directory). Use `--project /path/to/repo` when querying a different project. The index lives at `{project}/.codeindex/index.db`.

## Notes

- The index is not a substitute for `grep` on content — use it for structure (what exists, where, how things connect).
- `search` uses FTS5 BM25 — results are ranked by relevance, most relevant first.
- When the index is stale, re-run `codeindex index <dir>` first.
- `.codeindex/.gitignore` is created automatically on first use; the directory is self-contained.
