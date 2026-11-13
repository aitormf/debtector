# `debtector diff` schema

`debtector diff <db_base> <db_pr> [--json]` compares two indexes with the rules of
`baseline status` (D-0008). Thresholds come from `debtector.toml` of `--project`.

With `--json` it prints one object with one key per section, each a list (empty if
nothing changed). Without changes the text output is `No architectural changes`.

| Key | Item |
|---|---|
| `new_cycles` | list of module paths of a cycle present in the PR, not in the base |
| `resolved_cycles` | same, for a cycle present in the base, not in the PR |
| `new_god_modules` | file path of a module that is a god module only in the PR |
| `resolved_god_modules` | file path of a module that was a god module only in the base |
| `new_sdp_violations` | `{source, target, source_instability, target_instability}` only in the PR |
| `resolved_sdp_violations` | same, only in the base |
| `instability_regressions` | `{file_path, metric: "instability", before, after}` |
| `worsened_functions` | `{qualified_name, file_path, before, after, severity}`: complexity in the PR is `>= complexity_medium` and the function is new (`before: null`) or its complexity grew; `severity` is that of `after` |
| `improved_functions` | same: it was `>= complexity_medium` in the base and in the PR it is below it or gone (`after: null`); `severity` is that of `before` |
| `new_hotspots` | `{file_path, churn, complexity, hotspot_score, severity}`: the file is an actionable hotspot in the PR and was not in the base |
| `worsened_hotspots` | `{file_path, churn, complexity_before, complexity_after, severity_before, severity}`: actionable `medium` in the base and `high` in the PR |
| `skipped` | list of `{section, reason}` for what could not be computed; empty if nothing was skipped. Today only `hotspots`, in a shallow clone |

Rules:

- A cycle is identified by its set of modules: the same cycle in another order is not new.
- Ca and Ce count distinct internal modules: external imports (no File in the index) and repeated imports of the same module do not add to them (metrics version 2).
- SDP violations ignore pure facades: an `__init__.py` with no classes or functions is neither source nor target (metrics version 4).
- A module that exists only in one index is never an instability regression.
- An instability regression needs `after > before + 0.05` (a delta of exactly 0.05 is not one).
- Functions are identified by `qualified_name` (a rename is a removal plus a new function). Only production functions and methods count; test files are ignored. Thresholds are `[audit.thresholds]` `complexity_medium` / `complexity_high`. Complexity is informational: it never changes the exit code.
- Hotspots use `select_actionable_hotspots` (D-0007) with the `[audit.thresholds]` `hotspot_*` keys, once per side. The churn (commits of the file) is the one of the repository of `--project` on both sides: only the complexity differs. They are informational and never change the exit code.
- In a shallow clone (`git clone --depth 1`, the default of CI checkouts) the churn is truncated: `new_hotspots` and `worsened_hotspots` are empty and `skipped` has an item for `hotspots` with the reason. The rest of the diff works as usual. Fetch the full history (`fetch-depth: 0`) to get hotspots.
