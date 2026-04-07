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

If the command is not found: `pip install codeindex` or `uv add codeindex`.

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

If results look correct, the index is ready.

## Step 6 — Add to .gitignore (optional but recommended)

The `.codeindex/` directory should typically NOT be committed (it's a local cache):

```
# .gitignore
.codeindex/
```

## Step 7 — Set up incremental indexing

After any editing session, refresh the index:

```bash
codeindex index <source_root>
```

Only changed files are re-parsed (incremental by default, based on file hash).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `files: 0` after indexing | Wrong source root | Try `codeindex index src/` or `codeindex index .` |
| `errors: N` | Parse failures | Check `.codeindex/codeindex.log` for details |
| Missing TypeScript nodes | `.ts` files not in source root | Confirm path includes `.ts` files |
| Stale results | Files edited after last index | Run `codeindex index <source_root>` again |
| `index.db` not found for other commands | Ran index from different directory | Use `--project` flag or `cd` to project root |

## Supported languages

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |

More languages (Go, Rust, Java) can be added via custom parsers.
