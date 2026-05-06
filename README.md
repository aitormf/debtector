# Debtector

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python](https://img.shields.io/badge/Python-%E2%89%A53.12-blue)](https://www.python.org/)

[Leer en Español](README.es.md)

**Coupling guardrail for CI/PR.** Debtector indexes a code repository as a graph in SQLite, computes structural coupling metrics (Ca, Ce, instability, cycles, god modules) and behavioral ones (churn, hotspots, temporal coupling, bus factor), and blocks merges when metrics regress.

ICP: dev/tech lead using code agents. Agents generate hidden coupling faster than any human can track; Debtector acts as an architectural guardrail in the pipeline.

```bash
# Full report: structural coupling + git history
debtector report

# Typical CI flow: index, save baseline, check for regressions
debtector index ./src
debtector baseline save
debtector baseline status   # exit 1 if new cycles or coupling worsens
```

---

## Installation

Debtector is a **command-line tool**, not a library. Install it globally to use it across projects.

### With uv (recommended)

```bash
uv tool install /path/to/codeIndex
```

`uv tool install` does not support editable mode. To reflect code changes, reinstall with `--force` (it's fast):

```bash
uv tool install /path/to/codeIndex --force
```

### With pip

```bash
# Standard installation
pip install /path/to/codeIndex

# Editable — code changes are reflected immediately without reinstalling
pip install -e /path/to/codeIndex
```

Verify it is available globally:

```bash
debtector --help
which debtector
```

**Requirements:** Python ≥ 3.12

---

## Quick start

```bash
# 1. Index the project (incremental: only re-parses changed files)
debtector index ./src

# 2. View structural coupling
debtector coupling

# 3. View git history metrics (hotspots, temporal coupling, bus factor)
debtector git-coupling

# 4. Full report (structural + behavioral)
debtector report

# 5. Save baseline (commit .debtector/baseline.json to the repo)
debtector baseline save
git add .debtector/baseline.json && git commit -m "chore: save metrics baseline"

# 6. In CI: verify metrics have not regressed
debtector baseline status
```

> **Note:** analysis commands (`coupling`, `git-coupling`, `report`, `impact`, etc.) silently auto-index if there are modified files. There is no need to run `index` manually in the normal workflow.

The index lives in `.debtector/index.db`. The baseline in `.debtector/baseline.json`. Logs in `.debtector/debtector.log`.

---

## Commands

### Indexing

| Command | Description |
|---------|-------------|
| `index <dir>` | Index the directory (incremental by SHA-256 hash) |
| `status` | Graph statistics (files, nodes, edges by type) |

### Code analysis

| Command | Description |
|---------|-------------|
| `search <query>` | Search symbols by name (FTS5 + BM25). `--kind Class\|Function\|Method` to filter |
| `summary <file>` | All symbols and imports in a file |
| `impact <files...>` | Which files and nodes are affected by a change. `--depth N` |
| `imports <module>` | Which files import a module or library |
| `callers <qname>` | Which functions/methods call a specific symbol |
| `untested [path]` | Production symbols with no test coverage |

### Structural coupling

| Command | Description |
|---------|-------------|
| `coupling` | Ca, Ce, I table per module + cycles + god modules. `--sort fan_in\|fan_out\|instability`, `--limit N`, `--json` |
| `baseline save` | Save metrics snapshot to `.debtector/baseline.json` |
| `baseline status` | Compare current metrics against the baseline. Exit 1 on regressions (configurable) |
| `baseline status --reporter github` | Same but emits GitHub Actions Annotations (`::error/::warning`) |
| `baseline status --reporter gitlab` | Same but emits GitLab CI section markers |

### Behavioral coupling (git history)

| Command | Description |
|---------|-------------|
| `hotspots` | Technical debt ranking: churn × (fan_in + fan_out). `--limit N`, `--since DATE` |
| `temporal-coupling` | File pairs that change together without a direct import. `--min-shared N`, `--min-ratio F`, `--since DATE` |
| `bus-factor` | Knowledge concentration risk: % of lines by dominant author. `--limit N` |
| `git-coupling` | Aggregated view of the three above. `--json` combines all three sections |
| `report` | Full report: structural + behavioral coupling. `--json` for AI/CI consumption |

### Configuration and hooks

| Command | Description |
|---------|-------------|
| `install-hook` | Git pre-commit hook for auto-indexing |
| `install-skill` | Claude Code skills for using the graph in AI context |

### Global flag `--json`

All commands support `--json` to emit compact JSON to stdout, suitable for direct consumption by AI agents or pipelines:

```bash
debtector --json coupling
debtector --json report
debtector --json hotspots --limit 10
debtector --json baseline status
debtector --json search "AuthService"
```

---

## Available metrics

### Structural coupling (`debtector coupling`)

| Metric | Description |
|--------|-------------|
| **Ca (fan-in)** | How many modules depend on this one. Weight 1.0 per `IMPORTS_FROM` and `USES_TYPE` |
| **Ce (fan-out)** | How many modules this one imports. Same weight scheme |
| **I (instability)** | `Ce / (Ca + Ce)`. 0 = very stable, 1 = very unstable |

Example output:

```
Module                      Ca      Ce       I    Flags
──────────────────────────────────────────────────────
src/graph_store.py        12.0     3.0   0.200
src/cli.py                 0.0    14.5   1.000  ⚠ unstable
src/models.py              9.5     0.0   0.000  ● god
──────────────────────────────────────────────────────
Total: 8 modules

✓  No cycles
● God modules (Ca > p90): src/models.py
```

### Cycles

Import cycle detection using Tarjan's algorithm (SCCs). Considers `IMPORTS_FROM` and `CALLS` edges.

### God modules

Modules whose fan-in exceeds the 90th percentile of the project. Relative threshold, not absolute.

### Inheritance (`debtector coupling --json`)

Inheritance hierarchy depth and number of direct children per class.

### Behavioral coupling (`debtector git-coupling`)

| Metric | Description |
|--------|-------------|
| **Hotspot score** | `churn × (fan_in + fan_out)`. The most changed and most coupled modules carry the highest technical debt risk |
| **Temporal coupling** | File pairs that appear together in commits more frequently than a configurable threshold, even without a direct `import` between them |
| **Bus factor** | Minimum number of authors needed to cover 80% of the lines in a file. 1 = single point of failure |

Example output of `debtector hotspots`:

```
Module                            Churn  Coupling     Score
────────────────────────────────────────────────────────────
src/graph_store.py                   47      15.00    705.00
src/cli.py                           31      14.50    449.50
src/parser/python_parser.py          28       3.00     84.00
────────────────────────────────────────────────────────────
Total: 8 hotspots
```

---

## Ratcheting in CI

The typical CI flow is:

```yaml
# .github/workflows/ci.yml
- name: Check coupling ratchet
  run: |
    debtector index ./src
    debtector baseline status --reporter github
```

- If `baseline.json` does not exist → exit 0 (silent mode, does not block)
- If it exists and metrics are equal or improve → exit 0
- If there are new cycles, new god modules, or instability worsens → exit 1

### Severity configuration (`debtector.toml`)

```toml
[metrics.thresholds]
god_module_percentile = 90    # percentile for god module
instability_threshold = 0.8   # I >= threshold → warning in table

[metrics.severity]
cycles      = "error"    # blocks CI
god_modules = "warning"  # warns but does not block
instability = "warning"  # warns but does not block
inheritance = "info"     # info only
```

Severities: `error` (exit 1) · `warning` (prints, exit 0) · `info` (silent, exit 0).

---

## Supported languages

| Language | Extensions |
|----------|------------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |

---

## Graph edge types

| Type | Description |
|------|-------------|
| `CONTAINS` | File → class/function |
| `HAS_METHOD` | Class → method |
| `IMPORTS_FROM` | File → imported module (weight 1.0 in Ca/Ce) |
| `INHERITS` | Class → base class |
| `CALLS` | Function/method → called function/method |
| `COVERS` | Test function → production symbol it exercises |
| `USES_TYPE` | Function → type referenced in type hints (weight 1.0 in Ca/Ce) |

---

## `.debtector/` directory

```
.debtector/
  index.db        # SQLite graph (committable if you want to share it)
  baseline.json   # metrics snapshot (commit to repo)
  debtector.log   # structured logs (git-ignored)
  .gitignore      # auto-generated
```

The `.debtector/.gitignore` is managed by Debtector: ignores everything except `baseline.json` and the `.gitignore` itself.

---

## Auto-indexing with git hook

```bash
debtector install-hook              # re-indexes on each pre-commit
debtector install-hook --add-to-stage  # also stages index.db
```

The hook is incremental (only re-parses files with a different hash) and never blocks a commit.

---

## Claude Code integration

```bash
debtector install-skill --global   # installs in ~/.claude/skills/
debtector install-skill            # installs in .claude/skills/ of the project
```

With the skills installed, Claude Code recognizes phrases like *"analyze the impact of changing AuthService"* or *"who imports flask?"* and automatically calls the CLI with `--json`.

---

## Development

```bash
git clone https://github.com/aitormf/codeIndex
cd codeIndex
uv sync --dev

uv run pytest                     # tests
uv run ruff check .               # linter
uv run ruff format .              # formatter
uv run bandit -r src/             # security

# Install pre-commit hooks (three stages required)
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
uv run pre-commit install --hook-type pre-push
```

---

## Logging

```bash
DEBTECTOR_LOG_JSON=false debtector index ./src   # colored (default)
DEBTECTOR_LOG_JSON=true  debtector index ./src   # JSON lines (prod/observability)
```

Logs always go to `.debtector/debtector.log`, never to stdout.

---

## Roadmap

- [x] FTS5 — lexical/ranked search
- [x] CALLS — intra-file call edges
- [x] COVERS + `debtector untested` — test coverage
- [x] `.debtectorignore` — additional ignored paths
- [x] **Ca, Ce, instability** — coupling metrics per module
- [x] **Cycles** — detection with Tarjan's algorithm
- [x] **God modules** — fan-in outliers (90th percentile)
- [x] **Inheritance** — depth and number of children
- [x] **USES_TYPE** — type hint coupling (weight 1.0)
- [x] **`debtector coupling`** — tabular output with flags (formerly `metrics`)
- [x] **Baseline + ratcheting** — CI only fails if metrics worsen
- [x] **Configurable severity** — `debtector.toml` error/warning/info per type
- [x] **CI reporter** — GitHub Annotations + GitLab CI section markers
- [x] **Silent auto-index** — analysis commands index before executing
- [x] **Hotspots** — churn × structural coupling; real technical debt ranking
- [x] **Temporal coupling** — files that co-change without a direct import
- [x] **Bus factor** — knowledge concentration risk per file
- [x] **`debtector git-coupling` / `report`** — aggregated behavioral and full views
- [ ] Graph diff — metric delta between base branch and PR
- [ ] GitHub Action — automatic comment on PRs
- [ ] More languages — Go, Rust, Java

## License

AGPL-3.0 — see [LICENSE](LICENSE).
