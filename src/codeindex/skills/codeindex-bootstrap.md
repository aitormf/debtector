---
name: codeindex-bootstrap
description: First-time setup of CodeIndex for a project — detect languages, run initial indexing, verify the index, and guide the user through first queries.
triggers:
  - setup codeindex
  - index this repo
  - initialise codeindex
  - bootstrap codeindex
  - codeindex for the first time
  - start using codeindex
---

# CodeIndex Bootstrap — First-Time Setup

Follow these steps to set up CodeIndex for a project that has not been indexed yet.

## Step 1 — Verify installation

```bash
codeindex --help
```

If the command is not found:
```bash
uv add codeindex        # preferred (uv project)
pip install codeindex   # fallback
```


## Step 2 — Detect project structure

Before indexing, identify the source root (avoid indexing `node_modules`, `venv`, `.git`, build outputs):

```bash
ls -la
```

Look for `src/`, `lib/`, `app/`, or the package directory. Common source roots:
- Python: `src/`, or the package directory itself
- JavaScript/TypeScript: `src/`, `lib/`, `app/`
- Monorepo: index each package separately

## Step 3 — Run initial indexing

```bash
codeindex index <source_root>
```

Example outputs to expect:
- `indexed: N` — files parsed and stored
- `errors: 0` — no parse failures (investigate if > 0)
- `skipped: 0` — expected on first run

The index is stored at `.codeindex/index.db` in the current directory.
Logs go to `.codeindex/codeindex.log`.
A `.codeindex/.gitignore` is created automatically — no manual setup needed.

## Step 4 — Verify the index

```bash
codeindex --json status
```

Check that:
- `files` > 0
- `total_nodes` > 0
- `languages` includes the expected languages (`python`, `javascript`, `typescript`)

If `files` is 0: the source root path may be wrong, or files use unsupported extensions.

## Step 5 — Run a smoke test

```bash
# Find a class you know exists
codeindex --json search "<KnownClassName>"

# List symbols in a specific file
codeindex --json summary <path/to/known/file.py>
```

The `search` command uses FTS5 full-text search with BM25 ranking and camelCase splitting,
so `"UserService"` will match even when you only type `"user service"` or `"userserv"`.

If results look correct, the index is ready.

## Step 6 — Install skills into Claude Code

```bash
codeindex install-skill              # project-level (.claude/skills/)
codeindex install-skill --global     # user-level (~/.claude/skills/)
```

This copies `codeindex.md` and `codeindex-bootstrap.md` so Claude Code triggers them automatically for future sessions. No restart needed.

## Step 7 — Set up git pre-commit auto-indexing (recommended)

```bash
codeindex install-hook
```

Installs a `pre-commit` git hook that runs `codeindex index .` before every commit — keeping the index always up to date without manual intervention.

If you want the updated `index.db` to be committed alongside your code changes:
```bash
codeindex install-hook --add-to-stage
```

The hook is idempotent: running it twice has no effect.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `files: 0` after indexing | Wrong source root | Try `codeindex index src/` or `codeindex index .` |
| `errors: N` | Parse failures | Check `.codeindex/codeindex.log` for details |
| Missing TypeScript nodes | `.ts` files not in source root | Confirm path includes `.ts` files |
| Stale results | Files edited after last index | Run `codeindex index <source_root>` again |
| `index.db` not found for other commands | Ran index from different directory | Use `--project` flag or `cd` to project root |
| `search` returns unexpected results | FTS5 BM25 ranking | Results are relevance-ranked; add `--kind` to narrow |
| `embeddings_count: 0` in status | sqlite-vec failed to load | Check Python version (≥ 3.10) and reinstall: `uv sync` |

## Supported languages

| Language | Extensions |
|----------|------------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |

More languages (Go, Rust, Java) can be added via custom parsers.
