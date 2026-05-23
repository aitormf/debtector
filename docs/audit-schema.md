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
| `modules`      | int  | Number of indexed files.                                |
| `cycles`       | int  | Number of strongly-connected components of size > 1.    |
| `classes`      | int  | Number of indexed `Class` nodes.                        |
| `health_score` | int  | Aggregate score in `[0, 100]` (see Health score below). |

## `coupling`

Array of module-level coupling entries, sorted by `fan_in` descending.

| field         | type    | meaning                                                |
|---------------|---------|--------------------------------------------------------|
| `file_path`   | string  | Relative path of the module.                           |
| `fan_in`      | number  | Ca: weighted incoming imports.                         |
| `fan_out`     | number  | Ce: weighted outgoing imports.                         |
| `instability` | number  | `Ce / (Ca + Ce)` in `[0.0, 1.0]`.                      |
| `god_module`  | boolean | `true` when `fan_in` is above the project's percentile. |

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
factor.

| field                              | type            | meaning                                          |
|------------------------------------|-----------------|--------------------------------------------------|
| `untested_high_coupling`           | array of string | Files with no `COVERS` and Ce above threshold.   |
| `untested_hotspots`                | array of string | Files with no `COVERS` and churn above threshold.|
| `critical_knowledge_concentration` | array of string | Bus factor 1 files with Ca above threshold.      |

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

Severity buckets and 0-100 score. A clean graph scores `100`.

| severity   | source signals                                                            | penalty |
|------------|---------------------------------------------------------------------------|---------|
| `critical` | cycles, `critical_knowledge_concentration`                                | 15      |
| `high`     | `candidate_to_split` classes, `untested_high_coupling`, `untested_hotspots`| 5       |
| `medium`   | `god_module` entries, hotspots                                            | 2       |
| `low`      | single-author files (`busFactor` rows)                                    | 0.5     |

`score = max(0, 100 − Σ penalty × count)` (rounded to int).

## Example payload

```json
{
  "schema_version": 1,
  "summary": {"modules": 12, "cycles": 0, "classes": 4, "health_score": 92},
  "coupling": [
    {"file_path": "src/app.py", "fan_in": 5, "fan_out": 3, "instability": 0.375, "god_module": false}
  ],
  "cycles": [],
  "cohesion": [
    {"qualified_name": "src/app.py::Service", "lcom4": 1, "methods_count": 4, "candidate_to_split": false}
  ],
  "testRisk": {"untested_high_coupling": [], "untested_hotspots": [], "critical_knowledge_concentration": []},
  "hotspots": [],
  "busFactor": [],
  "inheritance": []
}
```
