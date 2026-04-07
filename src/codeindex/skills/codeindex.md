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

## Command reference

### status — index health check
```bash
codeindex --json status
```
Returns: `{"files": N, "total_nodes": N, "total_edges": N, "languages": [...], "nodes_by_kind": {...}, "edges_by_kind": {...}}`

Run this first to confirm the index exists and is non-empty.

---

### search — find symbols by name
```bash
codeindex --json search "<query>"
codeindex --json search "<query>" --kind Class   # or Function, Method
```
Returns: array of `{kind, name, qualified_name, file_path, line_start, line_end, signature}`

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

---

### index — refresh the index
```bash
codeindex index <directory>
codeindex --json index <directory>
```
Run after editing files. Incremental — only re-parses changed files (based on SHA-256 hash). JSON returns `{scanned, indexed, skipped, errors, removed}`.

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

## Project path

By default `--project` is `.` (current directory). Use `--project /path/to/repo` when querying a different project. The index lives at `{project}/.codeindex/index.db`.

## Notes

- The index is not a substitute for `grep` on content — use it for structure (what exists, where, how things connect).
- `callers` only shows CALLS edges; if CALLS edges are not yet populated, use `imports` + `search` to trace manually.
- When the index is stale, re-run `codeindex index <dir>` first.
