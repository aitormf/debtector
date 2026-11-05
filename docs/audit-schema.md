# `debtector audit --json` — Schema v1

Stable JSON contract for the audit surface (Fase 3, see
[ADR-003](decisions/003-audit-as-second-surface.md)). Consumers (IDE plugins,
AI orchestrators, dashboards) may depend on this shape.

The contract evolves through `schema_version`. Breaking changes (renames,
removed fields, changed semantics) bump the integer. New additive fields do
not.

## Top-level shape

```json
{
  "schema_version": 1,
  "summary": {...},
  "coupling": [...],
  "cycles": [...],
  "cohesion": [...],
  "testRisk": {...},
  "hotspots": [...],
  "busFactor": [...],
  "inheritance": [...]
}
```

The eight sections appear in this exact order. List sections are capped to
the CLI's `--top-n` (default: 10) unless `--full` is passed.

## `schema_version`

Integer. Currently `1`. Increment on any breaking change.

## `summary`

Object. Aggregate counts and the health score for the whole index.

| field          | type | meaning                                                 |
|----------------|------|---------------------------------------------------------|
| `modules`      | int  | Indexed files, excluding `test_paths` files outside the index. |
| `cycles`       | int  | Number of strongly-connected components of size > 1.    |
| `classes`      | int  | Number of indexed `Class` nodes.                        |
| `health_score` | int  | Aggregate score in `[0, 100]` (see Health score below). |
| `health_score_version` | int | Meaning of `health_score`; currently `2`. Absent in version 1. |

## `coupling`

Array of module-level coupling entries, sorted by `fan_in` descending.

| field         | type    | meaning                                                |
|---------------|---------|--------------------------------------------------------|
| `file_path`   | string  | Relative path of the module.                           |
| `fan_in`      | number  | Ca: weighted incoming imports.                         |
| `fan_out`     | number  | Ce: weighted outgoing imports.                         |
| `instability` | number  | `Ce / (Ca + Ce)` in `[0.0, 1.0]`.                      |
| `god_module`  | boolean | `true` when `fan_in` is above the project's percentile and at least `god_module_min_ca` (default 10). |

## `cycles`

Array of detected import cycles, prioritised by the fan-in of the most
exposed node ("break first" first).

| field      | type            | meaning                                            |
|------------|-----------------|----------------------------------------------------|
| `nodes`    | array of string | Members of the cycle (qualified names).            |
| `pivot`    | string          | Most-exposed member (highest external Ca).         |
| `pivot_ca` | number          | External fan-in of the pivot node.                 |
| `rationale`| string          | `"break first"` for the top entry, else `"follow-up"`. |

## `cohesion`

Array of per-class LCOM4 cohesion entries.

| field                | type    | meaning                                                |
|----------------------|---------|--------------------------------------------------------|
| `qualified_name`     | string  | Fully-qualified class id.                              |
| `lcom4`              | int     | Connected components of intra-class `CALLS`. `1` is cohesive. |
| `methods_count`      | int     | Number of methods declared in the class.               |
| `candidate_to_split` | boolean | `true` when `lcom4 > 1`.                               |

## `testRisk`

Object with three buckets cross-joining coverage, coupling, churn and bus
factor, plus a `status` flag.

| field                              | type            | meaning                                          |
|------------------------------------|-----------------|--------------------------------------------------|
| `status`                           | string          | `"ok"`, or `"skipped"` when no test files were found (see below). |
| `reason`                           | string          | Only present when `status` is `"skipped"`: `"no_tests_found"`. |
| `untested_high_coupling`           | array of string | Files with no `COVERS` and Ce above threshold.   |
| `untested_hotspots`                | array of string | Files with no `COVERS` and churn above threshold.|
| `critical_knowledge_concentration` | array of string | Bus factor 1 files with Ca above threshold.      |

When no test file is indexed (neither files matching the test conventions nor
files under `test_paths` in `debtector.toml`), every file would look
"uncovered". In that case the `untested_*` joins are not computed: `status` is
`"skipped"`, `reason` is `"no_tests_found"`, `untested_high_coupling` and
`untested_hotspots` are empty and they do not affect `health_score`.
`critical_knowledge_concentration` does not depend on tests and is still
computed. Consumers that predate `status` can ignore it: the three buckets keep
their shape. In human output the same condition prints a warning on stderr.

Files under `test_paths` that lie outside the indexed directory are stored with
a `../`-prefixed path and are excluded from `coupling` and `summary` metrics.

## `hotspots`

Array of churn × coupling hotspots with score > 0.

| field       | type   | meaning                                          |
|-------------|--------|--------------------------------------------------|
| `file_path` | string | Relative file path.                              |
| `churn`     | int    | Recent commit count.                             |
| `score`     | number | Composite hotspot score.                         |

## `busFactor`

Array of single-author files (`bus_factor == 1`).

| field         | type   | meaning                                       |
|---------------|--------|-----------------------------------------------|
| `file_path`   | string | Relative file path.                           |
| `top_author`  | string | Highest-share author.                         |
| `bus_factor` | int    | Authors needed to cover ≥50% of churn (always `1` here). |

## `inheritance`

Array of class-level inheritance metrics.

| field            | type   | meaning                                       |
|------------------|--------|-----------------------------------------------|
| `qualified_name` | string | Class id.                                     |
| `depth`          | int    | Distance to the deepest ancestor (0 = root).  |
| `children`       | int    | Number of direct subclasses.                  |

## Health score

Severity buckets and 0-100 score. A project with no scored findings scores `100`.
This is **health score version 2** (`summary.health_score_version`).

| severity   | source signals (scored)                                                   | penalty |
|------------|---------------------------------------------------------------------------|---------|
| `critical` | `critical_knowledge_concentration` (not in single-author repos, see below) | 15      |
| `high`     | `untested_high_coupling`, `untested_hotspots`                             | 5       |
| `medium`   | actionable hotspots (see below)                                           | 2       |
| `low`      | none                                                                      | 0.5     |

Not scored: `cycles`, `god_module` entries, `busFactor` rows (single-author files) and
`cohesion`. They are reported in their sections only. `cohesion` is informational because
`lcom4` only links methods through `CALLS`, not through shared attributes, so cohesive
classes can show `lcom4 > 1`.

**Formula.** The penalty is normalised by project size:

`score = max(0, 100 − 100 · Σ penalty × count / (5 · modules))` (rounded to int),

where `modules` is `summary.modules`. On average one `high` finding per module scores `0`.
With `modules == 0` the score is `100`.

**Actionable hotspots.** The `hotspots` section keeps listing the top-N as before, but only
hotspots with `score` at or above **both** the project's `hotspot_percentile` (default 90) of
the hotspot scores **and** `hotspot_min_score` (default 20, i.e. commits × (Ca + Ce), for
example 5 commits on a module with coupling 4) count towards the score.

**Single author.** If the whole repository's commit history (not just the indexed directory) has exactly one author, bus factor 1 is
meaningless. Shallow clones (e.g. `fetch-depth: 1` in CI) never get this exemption, since
their history is truncated and authorship is unknown. Bot accounts (names ending in `[bot]`,
e.g. `github-actions[bot]`) are ignored when counting authors. Authors are counted by name as
`git log` reports it (honouring `.mailmap`): a person with several name variants should add a
`.mailmap` so they count once. In the exempt case, `critical_knowledge_concentration` entries are still listed in `testRisk` (and
`busFactor` is unchanged) but do not count towards the score.

**Configuration** (`debtector.toml`, all optional):

```toml
[audit.thresholds]
testrisk_high_ce    = 10   # untested_high_coupling: Ce >=
testrisk_high_churn = 5    # untested_hotspots: commits >=
testrisk_high_ca    = 10   # critical_knowledge_concentration: Ca >=
hotspot_percentile  = 90   # in [1, 99]
hotspot_min_score   = 20
```

**Versioning.** Version 2 changes what `health_score` means (scores are not comparable with
version 1). Rather than bump `schema_version` (the shape of the payload is unchanged), the
additive field `summary.health_score_version` (`2`) lets consumers detect it; its absence
means version 1.

## Example payload

```json
{
  "schema_version": 1,
  "summary": {"modules": 12, "cycles": 0, "classes": 4, "health_score": 92, "health_score_version": 2},
  "coupling": [
    {"file_path": "src/app.py", "fan_in": 5, "fan_out": 3, "instability": 0.375, "god_module": false}
  ],
  "cycles": [],
  "cohesion": [
    {"qualified_name": "src/app.py::Service", "lcom4": 1, "methods_count": 4, "candidate_to_split": false}
  ],
  "testRisk": {"status": "ok", "untested_high_coupling": [], "untested_hotspots": [], "critical_knowledge_concentration": []},
  "hotspots": [],
  "busFactor": [],
  "inheritance": []
}
```
