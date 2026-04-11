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
  - semantic search
  - find code that
  - what handles
  - where is the logic for
  - which code deals with
  - find similar code
  - how does this work
  - how does X work
  - explain this module
  - explain the codebase
  - give me an overview
  - understand the codebase
  - understand this code
  - before I change
  - before changing
  - what could break
  - what might break
  - orient me
  - where should I start
  - familiarize with
  - get familiar with
  - new to this codebase
  - starting a new task
  - what changed could affect
  - what did I break
---

# CodeIndex — Code Graph Query Tool

CodeIndex maintains a structural graph of the codebase stored in `.codeindex/index.db`.
Use `codeindex --json <subcommand>` to query it. All output is compact JSON — parse it directly, do not re-read source files for information already in the index.

> **If you are unsure about flags, output format, or exact syntax for any command, run `codeindex <subcommand> --help` rather than guessing.**

## When to use each subcommand

| Goal | Command |
|------|---------|
| Find a class, function or method by name | `search` |
| Find symbols by meaning / concept | `semantic` |
| See all symbols and imports in one file | `summary` |
| Know which files are affected by a change | `impact` |
| Find who imports a library or module | `imports` |
| Find who calls a specific function/method | `callers` |
| Get overall stats (node/edge/embedding counts) | `status` |
| Refresh the index after editing files | `index` |

## Typical workflows

**Starting a new task — orient before touching anything:**
```bash
# 1. Get a feel for the file you'll be working on
codeindex --json summary path/to/file.py

# 2. Understand what it depends on
codeindex --json imports path/to/file.py

# 3. Find related symbols by concept (no need to know exact names)
codeindex --json semantic "user authentication flow"

# 4. Check who calls the functions you might change
codeindex --json callers "path/to/file.py::MyClass.my_method"
```
Use this flow before reading source files — in most cases it answers orientation questions at a fraction of the token cost.

---

**After making changes — verify blast radius:**
```bash
# Re-index first so the graph reflects your changes
codeindex index .

# What files are affected by what I just changed?
codeindex --json impact path/to/changed/file.py --depth 3

# Who calls the function I modified?
codeindex --json callers "path/to/file.py::changed_function"
```

---

**Before refactoring a public function:**
```bash
codeindex --json search "my_function" --kind Function
codeindex --json callers "path/to/file.py::my_function"
codeindex --json impact path/to/file.py --depth 3
```

---

**Finding code by concept:**
```bash
codeindex --json semantic "user authentication and token validation"
codeindex --json semantic "rate limiting middleware" --limit 5
```

---

**Checking library adoption:**
```bash
codeindex --json imports flask
codeindex --json imports ".database"   # relative imports
```

---

**After editing files:**
```bash
codeindex index .
codeindex --json status
```

## Project path

By default `--project` is `.` (current directory). Use `--project /path/to/repo` when querying a different project. The index lives at `{project}/.codeindex/index.db`.

## Notes

- The index is not a substitute for `grep` on content — use it for structure (what exists, where, how things connect).
- `search` uses FTS5 BM25 — results are ranked by relevance, most relevant first.
- `semantic` uses vector cosine distance — lower distance = more similar.
- When the index is stale, re-run `codeindex index <dir>` first.
- Use `.codeindexignore` (gitignore-style patterns) to exclude paths from indexing.
