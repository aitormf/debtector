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
uv tool install debtector
uv tool upgrade debtector   # later, to update
```

### With pip

```bash
pip install debtector
```

To work on debtector itself, see [Development](#development).

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
| `complexity` | Functions and methods sorted by cyclomatic complexity. `--limit N`, `--min N`, `--json` |
| `coupling` | Ca, Ce, I table per module + cycles + god modules. `--sort fan_in\|fan_out\|instability`, `--limit N`, `--json` |
| `baseline save` | Save metrics snapshot to `.debtector/baseline.json` |
| `baseline status` | Compare current metrics against the baseline. Exit 1 on regressions (configurable) |
| `baseline status --reporter github` | Same but emits GitHub Actions Annotations (`::error/::warning`) |
| `baseline status --reporter gitlab` | Same but emits GitLab CI section markers |

### Behavioral coupling (git history)

| Command | Description |
|---------|-------------|
| `hotspots` | Technical debt ranking: churn × cyclomatic complexity (coupling shown for context). `--limit N`, `--since DATE` |
| `temporal-coupling` | File pairs that change together without a direct import. `--min-shared N`, `--min-ratio F`, `--since DATE` |
| `bus-factor` | Knowledge concentration risk: % of lines by dominant author. `--limit N` |
| `git-coupling` | Aggregated view of the three above. `--json` combines all three sections |
| `report` | Full report: structural + behavioral coupling. `--json` for AI/CI consumption |

### Global flag `--json`

All commands support `--json` to emit compact JSON to stdout, suitable for direct consumption by AI agents or pipelines:

```bash
debtector --json coupling
debtector --json report
debtector --json hotspots --limit 10
debtector --json baseline status
debtector --json search "AuthService"
```

`--json` and `--project` are accepted before or after the sub-command (`debtector audit --json` is equivalent to `debtector --json audit`).

---

## Available metrics

### Structural coupling (`debtector coupling`)

| Metric | Description |
|--------|-------------|
| **Ca (fan-in)** | How many modules depend on this one. Weight 1.0 per `IMPORTS_FROM` and `USES_TYPE` |
| **Ce (fan-out)** | How many modules this one imports. Same weight scheme |
| **I (instability)** | `Ce / (Ca + Ce)`. 0 = very stable, 1 = very unstable. Reported for every module, but only flagged `⚠ unstable` when it is the target of a Stable Dependencies Principle (SDP) violation: a module imports another one whose I is higher by more than `sdp_margin`. A leaf with I = 1 is normal and not flagged |
| **God module** | Ca above the project's `god_module_percentile` **and** at least `god_module_min_ca` |

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
| **Hotspot score** | `churn × complexity`, where complexity is the sum of the cyclomatic (McCabe) complexity of the file's functions. The most changed and most complex files carry the highest technical debt risk |
| **Temporal coupling** | File pairs that appear together in commits more frequently than a configurable threshold, even without a direct `import` between them |
| **Bus factor** | Minimum number of authors needed to cover 80% of the lines in a file. 1 = single point of failure |

Example output of `debtector hotspots`:

```
Module                            Churn  Complexity   Coupling     Score
───────────────────────────────────────────────────────────────────────
src/cli.py                           31         290      14.50   8990.00
src/graph_store.py                   47         138      15.00   6486.00
src/parser/python_parser.py          28         130       3.00   3640.00
───────────────────────────────────────────────────────────────────────
Total: 8 hotspots
```

---

## Identifying files affected by a task

When you start from a natural-language description ("add rate limiting", "refactor the payments module") and need to know which files of the repo are involved, debtector provides deterministic data that narrows the search. The recommended flow is:

1. **Find candidates by keywords.** `debtector search` (FTS5 + BM25) returns symbols lexically related to the task, ranked by relevance:

   ```bash
   debtector --json search "rate limit"
   debtector --json search "AuthService" --kind Class
   ```

2. **Expand the impact radius.** Once seed files are identified, `debtector impact` performs BFS over the graph and returns every file and node that depends on them, directly or transitively:

   ```bash
   debtector --json impact src/auth/service.py
   debtector --json impact src/auth/service.py src/auth/middleware.py --depth 3
   ```

3. **Enrich with risk and coverage.** Crossing the resulting set with metrics and tests gives architectural context to prioritize what to read:

   ```bash
   debtector --json coupling             # which modules in the impact set are god / unstable
   debtector --json untested src/auth/   # which parts lack test coverage
   debtector --json hotspots             # which modules in the impact set accumulate debt
   ```

Each step emits stable JSON and composes easily from scripts, IDEs, CI or agents. Step 1 is lexical: if the task uses synonyms that do not appear in the code (e.g. "rate limiting" when the module is called `throttle`), the caller decides which candidates are relevant — debtector does not invent.

---

## Architectural diff in pull requests

`debtector diff --base <ref> --format markdown` compares the project with a git ref and prints a PR comment. The GitHub Action runs it on every pull request, publishes the result in a single comment that is updated on each push (new cycles, new god modules, new SDP violations, worsened complexity and hotspots), and always writes it to the job summary.

### Adding the GitHub Action to your repository

1. **Create the workflow** `.github/workflows/debtector.yml`:

   ```yaml
   name: debtector

   # Use pull_request, never pull_request_target: it would run PR code with a write token.
   on:
     pull_request:
       branches: [main]

   # One run per PR: a newer push cancels the older one, so two runs never race on the comment.
   concurrency:
     group: debtector-${{ github.event.pull_request.number }}
     cancel-in-progress: true

   permissions:
     contents: read
     pull-requests: write   # to create and update the comment

   jobs:
     diff:
       name: Architectural diff
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v6
           with:
             fetch-depth: 0   # the base commit and the history must be available
         - uses: aitormf/debtector@v0.30.0   # pin a release tag
           # with:
           #   fail-on-error: false   # default true: fail after commenting if the diff has `error` severity
           #   version: 0.30.0        # debtector version from PyPI; default: the version of the Action
           #   github-token: ${{ secrets.MY_TOKEN }}   # default: the job's GITHUB_TOKEN
   ```

2. **Check the token permissions.** The job asks for `pull-requests: write` itself. If your organization or repository restricts workflow permissions (*Settings → Actions → General → Workflow permissions*), allow that scope there too, or the Action will not be able to comment.

3. **Pin the version.** Use a release tag (`@vX.Y.Z`, see [releases](https://github.com/aitormf/debtector/releases)) rather than `@main`. The Action installs the debtector of that same tag unless you pass `version`.

4. **Decide what blocks the PR.** By default the job fails, after commenting, when the diff has something with `error` severity. Severities come from `debtector.toml` (see [Severity configuration](#severity-configuration-debtectortoml)); for example `cycles = "error"` blocks new cycles and `god_modules = "warning"` only reports them. Set `fail-on-error: false` to comment without ever failing.

5. **Optional: tune what is measured.**
   - `.debtectorignore` at the repository root excludes paths (generated code, `scripts/`, benchmarks, docs examples).
   - `test_paths` in `debtector.toml` if your tests do not follow the usual conventions (see [Test paths](#test-paths-debtectortoml)); test files never count as modules.

6. **Optional: require the check.** In the branch protection rule of `main`, add *Architectural diff* (the job `name`) as a required status check.

Notes:

- `fetch-depth: 0` matters. With the default shallow clone the history has one commit: the diff works, but hotspots are skipped (the comment says so).
- PRs from forks get a read-only token: there is no comment, the diff is in the job summary and the job does not fail because of that. Do not switch to `pull_request_target` to work around it.
- The Action is used on `ubuntu-latest`. It needs `bash` and `python3` on the runner (GitHub-hosted runners have both) and installs `uv` and debtector by itself.
- The Action complements the [baseline ratchet](#ratcheting-in-ci): the diff compares the PR with its base branch; the ratchet compares the current metrics with the committed `baseline.json`.

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
- If there are new cycles, new god modules, new SDP violations, or instability worsens → exit 1
- A baseline saved by an older version has no SDP data: SDP violations are not compared until you run `debtector baseline save` again

### Severity configuration (`debtector.toml`)

```toml
[metrics.thresholds]
god_module_percentile = 90    # percentile for god module
god_module_min_ca     = 10    # a god module also needs Ca >= this (absolute minimum)
sdp_margin            = 0.1   # I(B) - I(A) above this flags A -> B as an SDP violation
# instability_threshold is deprecated: still accepted, ignored (a warning is logged)

[metrics.severity]
cycles      = "error"    # blocks CI
god_modules = "warning"  # warns but does not block
complexity  = "warning"  # "error" blocks new or worsened functions with complexity >= complexity_medium
instability = "warning"  # warns but does not block
inheritance = "info"     # info only
```

Severities: `error` (exit 1) · `warning` (prints, exit 0) · `info` (silent, exit 0).

### Test paths (`debtector.toml`)

`audit` reports `testRisk` findings for files with no incoming `COVERS` edges. Test
files are detected by convention (`test_*`, `*_test.py`, `*.test.*`/`*.spec.*`, `tests/`, `test/`, `__tests__/`). If your
tests live elsewhere, or outside the directory you index (`debtector index ./src` with tests
in `./tests`), list them, relative to the project root:

```toml
test_paths = ["tests"]
```

Files under `test_paths` are test files in addition to the conventions, and are indexed even
when outside the indexed directory (they are not counted as modules in coupling metrics).
If no tests are found at all, `audit` skips the `untested *` findings (they do not affect the
health score), prints a warning on stderr and reports `"testRisk": {"status": "skipped", ...}`
in JSON.

### Audit calibration (`debtector.toml`)

The `audit` health score is normalised by project size (one `high` finding per module on
average scores 0) and only counts *actionable* hotspots: those at or above the project's
`hotspot_percentile` of the hotspot score and above `hotspot_min_score`. In a single-author
repository `critical_knowledge_concentration` is listed but not scored. Thresholds (defaults
shown):

```toml
[audit.thresholds]
testrisk_high_ce    = 10   # untested_high_coupling: Ce >=
testrisk_high_churn = 5    # untested_hotspots: commits >=
testrisk_high_ca    = 10   # critical_knowledge_concentration: Ca >=
hotspot_percentile  = 90   # percentile [1, 99] of the project's hotspot scores
hotspot_min_score   = 50   # absolute minimum: commits x file complexity
hotspot_high_factor = 3    # a hotspot is high from this multiple of the cut, else medium
complexity_medium   = 21   # function complexity from which it is a medium finding
complexity_high     = 31   # function complexity from which it is a high finding
```
Each production function or method at or above `complexity_medium` (`medium`) or
`complexity_high` (`high`) is also scored, and listed in the `complexity` section of
`debtector --json audit`; test files never count.

Authors are counted from the whole repository history by name (honouring `.mailmap`); bot
accounts (names ending in `[bot]`) are ignored. If one person commits under several name
variants, add a `.mailmap` so they count once; otherwise the repository looks multi-author.

See [`docs/audit-schema.md`](docs/audit-schema.md#health-score) for the full formula.

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

## Development

```bash
git clone https://github.com/aitormf/debtector
cd debtector
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
- [x] **`debtector audit`** — tech-lead view: health score, cohesion (LCOM4), testRisk, cycle priority ([schema](docs/audit-schema.md))
- [x] **Cyclomatic complexity per function** (`debtector complexity`) — churn × complexity hotspots
- [ ] Cognitive complexity per function
- [x] Graph diff — metric delta between base branch and PR (GitHub Action)
- [x] **Import resolution** — Python `src/` layout and `from pkg import submodule`, ESM `.js` → `.ts`, CommonJS `require()` anywhere, `export ... from` reexports, JS/TS barrels as facades
- [x] **Tests out of coupling metrics** — test files (`tests/`, `test/`, `__tests__/`, `*.test.*`, `*.spec.*`, `test_paths`) are not modules
- [x] **GitHub Action** — automatic comment on PRs, updated on each push ([setup](#adding-the-github-action-to-your-repository))
- [ ] More languages — Go, Rust, Java

## License

AGPL-3.0 — see [LICENSE](LICENSE).
