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

Rules:

- A cycle is identified by its set of modules: the same cycle in another order is not new.
- A module that exists only in one index is never an instability regression.
- An instability regression needs `after > before + 0.05` (a delta of exactly 0.05 is not one).
