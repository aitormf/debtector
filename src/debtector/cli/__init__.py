"""
Debtector CLI.

Usage:
    debtector index ./my-project
    debtector --json search "UserService"
    debtector summary src/auth/service.py
    debtector impact src/auth/service.py
    debtector imports flask
    debtector status
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess  # nosec B404 - runs git with a fixed argv, no shell
import sys
import tempfile
from pathlib import Path

import structlog

from ..config import Severity, load_config
from ..diff import (
    InvalidInputError,
    blocks_ci,
    check_comparable,
    compute_diff,
    instability_grew,
    validate_index,
)
from ..git_history import (
    compute_bus_factor,
    compute_hotspots,
    compute_temporal_coupling,
)
from ..graph_store import GraphStore
from ..indexer import Indexer
from ..logging import configure_logging
from ..metrics import (
    compute_metrics,
    find_cycles,
)
from ..render.diff_markdown import render_diff_markdown
from .common import (
    _INDEX_ROOT_KEY,
    _auto_index,
    _blocks,
    _configured_god_modules,
    _configured_sdp_violations,
    _debtector_dir,
    _get_store,
    _index_root,
    _json_out,
    _open_store,
    _print_section,
    _sdp_dict,
    _test_dirs,
    _test_prefixes,
    _warns,
)
from .graph import (
    cmd_callers,
    cmd_impact,
    cmd_imports,
    cmd_index,
    cmd_search,
    cmd_status,
    cmd_summary,
)
from .quality import cmd_audit, cmd_complexity, cmd_untested
from .reporters import _emit_github_annotations, _emit_gitlab_report, _sdp_text

log = structlog.get_logger()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# Baseline
# ──────────────────────────────────────────────

_BASELINE_FILE = ".debtector/baseline.json"


def _baseline_path(project: str) -> Path:
    return Path(project) / _BASELINE_FILE


_DIFF_SECTIONS = (
    ("new_cycles", "New cycles"),
    ("resolved_cycles", "Resolved cycles"),
    ("new_god_modules", "New god modules"),
    ("resolved_god_modules", "Resolved god modules"),
    ("new_sdp_violations", "New SDP violations"),
    ("resolved_sdp_violations", "Resolved SDP violations"),
    ("instability_regressions", "Instability regressions"),
    ("worsened_functions", "Functions with worse complexity"),
    ("improved_functions", "Functions with better complexity"),
    ("new_hotspots", "New hotspots"),
    ("worsened_hotspots", "Worsened hotspots"),
)


def _diff_item(item) -> str:
    if isinstance(item, dict) and "hotspot_score" in item:
        return (
            f"{item['file_path']}: churn {item['churn']}, "
            f"complexity {item['complexity']} ({item['severity']})"
        )
    if isinstance(item, dict) and "complexity_after" in item:
        return (
            f"{item['file_path']}: churn {item['churn']}, complexity "
            f"{item['complexity_before']} → {item['complexity_after']} "
            f"({item['severity_before']} → {item['severity']})"
        )
    if isinstance(item, list):
        return " → ".join(item) + " → ..."
    if isinstance(item, dict) and "qualified_name" in item:
        return f"{item['qualified_name']}: {item['before']} → {item['after']}"
    if isinstance(item, dict) and "metric" in item:
        return f"{item['file_path']}: {item['before']} → {item['after']}"
    if isinstance(item, dict):
        return f"{item['source']} → {item['target']}"
    return str(item)


def _git_out(cwd: str, *args: str) -> str:
    """Run ``git`` in *cwd* and return its stdout; :class:`InvalidInputError` if it fails."""
    try:
        proc = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", cwd, *args], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, OSError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        raise InvalidInputError(f"git {' '.join(args)} failed: {detail.strip()}") from e
    return proc.stdout.strip()


def _current_index_root(project: str) -> str:
    """Return the indexed directory of the project's index, relative to the project.

    Args:
        project: Path to the project root.

    Returns:
        The recorded ``index_root``, or ``"."`` for an empty (new) index.

    Raises:
        InvalidInputError: If the index has files but no recorded root (built by an
            older debtector): guessing it could rewrite every path, as in
            :func:`_auto_index`.
    """
    store = _get_store(project)
    try:
        rel = store.get_metadata(_INDEX_ROOT_KEY)
        if rel is None and store.get_all_files():
            raise InvalidInputError(
                "The current index has no recorded root (built by an older debtector); "
                "reindex it first: debtector index <dir>"
            )
    finally:
        store.close()
    return rel or "."


def _refresh_index(project: str) -> None:
    """Bring the project's index up to date, failing instead of comparing stale data.

    Unlike :func:`_auto_index`, a refresh that fails or skips files is an error: a
    diff against a partially updated index could hide a regression.

    Args:
        project: Path to the project root.

    Raises:
        InvalidInputError: If indexing raised or any file failed to index.
    """
    rel = _current_index_root(project)
    store = _get_store(project)
    try:
        try:
            stats = Indexer(store).index(str(Path(project) / rel), extra_paths=_test_dirs(project))
        except Exception as e:  # noqa: BLE001 - reported as invalid input, with the cause
            raise InvalidInputError(f"Could not refresh the current index: {e}") from e
        # A fresh index records its root, so later commands keep auto-refreshing it.
        store.set_metadata(_INDEX_ROOT_KEY, rel)
    finally:
        store.close()
    if stats["errors"]:
        raise InvalidInputError(
            f"Could not refresh the current index: {stats['errors']} file(s) failed "
            "(see .debtector/debtector.log)"
        )


def _index_base_ref(project: str, ref: str, db_path: str, worktree: Path) -> None:
    """Index *ref* of the project's repository into *db_path* through a temporary worktree.

    The worktree is always removed, also if indexing fails. The indexed directory
    is the same one (relative to the project) as in the current index, so the
    qualified names of both indexes match.

    Args:
        project: Path to the project root (inside a git repository).
        ref: Git ref to compare against (branch, tag or commit).
        db_path: Where to write the index of the ref.
        worktree: Directory for the temporary worktree; must not exist.

    Raises:
        InvalidInputError: If *project* is not in a git repository or *ref* does not exist.
    """
    # Physical path: git reports the real toplevel, and a symlinked alias would give a
    # relative path with ``..`` that escapes the worktree.
    project = os.path.realpath(project)
    toplevel = _git_out(project, "rev-parse", "--show-toplevel")
    try:
        _git_out(project, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except InvalidInputError as e:
        raise InvalidInputError(f"Unknown git ref: {ref}") from e
    submodules = _git_out(project, "submodule", "status", "--recursive")
    if any(line and not line.startswith("-") for line in submodules.splitlines()):
        # A new worktree leaves submodules empty: the base would miss their files.
        raise InvalidInputError(
            "--base does not support repositories with initialized submodules; "
            "index both revisions and run: debtector diff <db_base> <db_pr>"
        )
    real_top = os.path.realpath(toplevel)
    rel_project = Path(os.path.relpath(project, real_top))
    rel_root = _current_index_root(project)
    indexed = os.path.realpath(Path(project) / rel_root)
    if os.path.commonpath([indexed, real_top]) != real_top:
        # The worktree only contains the repository: the base would be empty.
        raise InvalidInputError(
            f"The indexed directory {indexed} is outside the git repository {real_top}; "
            "--base can only compare directories inside it"
        )
    try:
        # Inside the guard: a failing post-checkout hook makes ``worktree add`` report an
        # error after the worktree is already registered.
        _git_out(project, "worktree", "add", "--detach", str(worktree), ref)
        wt_project = worktree / rel_project
        store = GraphStore(db_path)
        try:
            store.test_prefixes = _test_prefixes(project, str(Path(project) / rel_root))
            extra = [str(wt_project / os.path.relpath(d, project)) for d in _test_dirs(project)]
            stats = Indexer(store).index(str(wt_project / rel_root), extra_paths=extra)
            if stats["errors"]:
                raise InvalidInputError(
                    f"Could not index {ref}: {stats['errors']} file(s) failed "
                    "(see .debtector/debtector.log)"
                )
            store.set_metadata(_INDEX_ROOT_KEY, rel_root)
        finally:
            store.close()
    finally:
        try:
            _git_out(project, "worktree", "remove", "--force", str(worktree))
        except InvalidInputError:
            # Never registered (``add`` failed early) or already gone: do not mask the
            # original error; ``prune`` drops a registration whose directory is gone.
            log.warning("diff_worktree_remove_failed", worktree=str(worktree), exc_info=True)
            _git_out(project, "worktree", "prune")


def cmd_diff(args) -> None:
    """Compare two indexes and report the architectural changes.

    Args:
        args: Parsed argument namespace. Expected attributes: ``project``
            (str, where ``debtector.toml`` lives), ``json`` (bool), ``db_base``
            and ``db_pr`` (str, paths to the two indexes).

    Exits with 2 if the inputs are not valid, and with 1 if something new has
    ``error`` severity in ``[metrics.severity]`` (D-0008).
    """
    cfg = load_config(args.project)
    base_ref = getattr(args, "base_ref", None)
    try:
        if base_ref and (args.db_base or args.db_pr):
            raise InvalidInputError("--base cannot be combined with index paths")
        if not base_ref and not (args.db_base and args.db_pr):
            raise InvalidInputError("pass --base <ref>, or the two indexes to compare")
        with tempfile.TemporaryDirectory(prefix="debtector-diff-") as tmp:
            db_base, db_pr = args.db_base, args.db_pr
            if base_ref:
                db_base = str(Path(tmp) / "base.db")
                _index_base_ref(args.project, base_ref, db_base, Path(tmp) / "worktree")
                _refresh_index(args.project)
                db_pr = str(_debtector_dir(args.project) / "index.db")
            validate_index(db_base)
            validate_index(db_pr)
            base, pr = _open_store(db_base, args.project), _open_store(db_pr, args.project)
            try:
                check_comparable(base, pr)
                result = compute_diff(base, pr, cfg, args.project)
            finally:
                base.close()
                pr.close()
    except InvalidInputError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    blocking = blocks_ci(result, cfg.metrics.severity)

    if args.json:
        _json_out(result)
    elif getattr(args, "format", "text") == "markdown":
        print(render_diff_markdown(result), end="")
    else:
        if not any(result[key] for key, _ in _DIFF_SECTIONS):
            print("No architectural changes")
        for key, title in _DIFF_SECTIONS:
            if result[key]:
                print(f"\n{title} ({len(result[key])}):")
                for item in result[key]:
                    print(f"   {_diff_item(item)}")
        for item in result["skipped"]:
            print(f"\nSkipped {item['section']}: {item['reason']}")
    if blocking:
        sys.exit(1)


def cmd_baseline(args) -> None:
    """Save or compare coupling metrics against a stored baseline.

    Sub-commands:

    * ``save``   — snapshot current metrics to ``.debtector/baseline.json``.
    * ``status`` — compare current metrics to the baseline and report regressions.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``baseline_cmd`` (str): ``"save"`` or ``"status"``.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    if args.baseline_cmd == "save":
        _baseline_save(args)
    elif args.baseline_cmd == "status":
        _baseline_status(args)
    else:
        print("Usage: debtector baseline <save|status>", file=sys.stderr)
        sys.exit(1)


def _baseline_save(args) -> None:
    """Snapshot current metrics to ``.debtector/baseline.json``."""
    cfg = load_config(args.project)
    store = _get_store(args.project)
    modules = compute_metrics(store)
    cycles = find_cycles(store)
    gods = _configured_god_modules(store, cfg)
    sdp = _configured_sdp_violations(store, cfg)
    store.close()

    snapshot = {
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "modules": [
            {
                "file_path": m.file_path,
                "fan_in": round(m.fan_in, 3),
                "fan_out": round(m.fan_out, 3),
                "instability": round(m.instability, 4),
            }
            for m in modules
        ],
        "cycles": cycles,
        "god_modules": [m.file_path for m in gods],
        "sdp_violations": [{"source": v.source, "target": v.target} for v in sdp],
    }

    path = _baseline_path(args.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if args.json:
        _json_out({"status": "saved", "path": str(path), "modules": len(modules)})
    else:
        print(f"Baseline saved: {path}  ({len(modules)} modules)")


def _baseline_status(args) -> None:
    """Compare current metrics to the stored baseline and report regressions.

    Each issue type (cycles, god_modules, instability) is filtered through the
    severity configured in ``debtector.toml``:

    - ``error``   — contributes to exit code 1 (blocks CI).
    - ``warning`` — printed but does not block CI (exit 0).
    - ``info``    — silent; neither printed nor blocking.
    """
    path = _baseline_path(args.project)

    if not path.exists():
        if args.json:
            _json_out({"error": "no baseline — run: debtector baseline save"})
        else:
            print("No baseline. Run first: debtector baseline save")
        return

    baseline = json.loads(path.read_text(encoding="utf-8"))
    baseline_cycles = [frozenset(c) for c in baseline.get("cycles", [])]
    baseline_gods = set(baseline.get("god_modules", []))

    cfg = load_config(args.project)
    sev = cfg.metrics.severity
    store = _get_store(args.project)
    current_modules = compute_metrics(store)
    current_cycles = find_cycles(store)
    current_gods = _configured_god_modules(store, cfg)
    current_sdp = _configured_sdp_violations(store, cfg)
    store.close()

    # Detect regressions by type
    new_cycles = [c for c in current_cycles if frozenset(c) not in baseline_cycles]
    new_gods = [m.file_path for m in current_gods if m.file_path not in baseline_gods]

    # SDP violations: a baseline predating this metric does not store them; without
    # prior data we cannot claim they got worse, so they are not compared.
    new_sdp: list[dict] = []
    if "sdp_violations" in baseline:
        known = {(v["source"], v["target"]) for v in baseline["sdp_violations"]}
        new_sdp = [_sdp_dict(v) for v in current_sdp if (v.source, v.target) not in known]

    regressions: list[dict] = []
    baseline_map = {m["file_path"]: m for m in baseline.get("modules", [])}
    for m in current_modules:
        prev = baseline_map.get(m.file_path)
        if prev is None:
            continue
        if instability_grew(prev["instability"], m.instability):
            regressions.append(
                {
                    "file_path": m.file_path,
                    "metric": "instability",
                    "before": prev["instability"],
                    "after": round(m.instability, 4),
                }
            )

    # Decide whether each regression type blocks CI according to its severity
    has_blocking = (
        _blocks(new_cycles, sev.cycles)
        or _blocks(new_gods, sev.god_modules)
        or _blocks(regressions, sev.instability)
        or _blocks(new_sdp, sev.instability)
    )

    if args.json:
        _json_out(
            {
                "regressions": regressions,
                "new_cycles": new_cycles,
                "new_god_modules": new_gods,
                "new_sdp_violations": new_sdp,
            }
        )
        if has_blocking:
            sys.exit(1)
        return

    has_any_warning = (
        _warns(new_cycles, sev.cycles)
        or _warns(new_gods, sev.god_modules)
        or _warns(regressions, sev.instability)
        or _warns(new_sdp, sev.instability)
    )

    reporter = getattr(args, "reporter", None)

    if not has_any_warning:
        print("✓  No changes from baseline")
        return

    if reporter == "github":
        _emit_github_annotations(new_cycles, new_gods, regressions, sev, new_sdp)
    elif reporter == "gitlab":
        _emit_gitlab_report(new_cycles, new_gods, regressions, sev, new_sdp)
    else:
        if _warns(new_cycles, sev.cycles):
            label = "⛔" if sev.cycles == Severity.ERROR else "⚠"
            print(f"\n{label}  New cycles ({len(new_cycles)}):")
            for cycle in new_cycles:
                print("   " + " → ".join(cycle) + " → ...")

        if _warns(new_gods, sev.god_modules):
            label = "⛔" if sev.god_modules == Severity.ERROR else "⚠"
            print(f"\n{label}  New god modules ({len(new_gods)}):")
            for path_str in new_gods:
                print(f"   {path_str}")

        if _warns(regressions, sev.instability):
            label = "⛔" if sev.instability == Severity.ERROR else "⚠"
            print(f"\n{label}  Instability regressions ({len(regressions)}):")
            for r in regressions:
                print(f"   {r['file_path']}  I: {r['before']:.3f} → {r['after']:.3f}")

        if _warns(new_sdp, sev.instability):
            label = "⛔" if sev.instability == Severity.ERROR else "⚠"
            print(f"\n{label}  New SDP violations ({len(new_sdp)}):")
            for v in new_sdp:
                print(f"   {_sdp_text(v)}")

    if has_blocking:
        sys.exit(1)


# ──────────────────────────────────────────────
# Structural coupling (ex-metrics)
# ──────────────────────────────────────────────


def cmd_coupling(args) -> None:
    """Print structural coupling metrics (Ca, Ce, I, cycles, god modules).

    Reads ``debtector.toml`` from the project root to apply configured
    thresholds.  With ``--json`` emits a single JSON object with keys
    ``modules``, ``cycles``, and ``god_modules``.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON instead of human-readable text.
            - ``sort`` (str): Column to sort by (``fan_in``, ``fan_out``,
              ``instability``). Default: ``fan_in``.
            - ``limit`` (int | None): Max rows to show. ``None`` = all.
    """
    _auto_index(args.project)
    cfg = load_config(args.project)
    store = _get_store(args.project)
    modules = compute_metrics(store)
    cycles = find_cycles(store)
    gods = _configured_god_modules(store, cfg)
    sdp = _configured_sdp_violations(store, cfg)
    store.close()

    god_paths = {m.file_path for m in gods}
    unstable_paths = {v.target for v in sdp}

    if args.json:
        _json_out(
            {
                "modules": [
                    {
                        "file_path": m.file_path,
                        "fan_in": round(m.fan_in, 2),
                        "fan_out": round(m.fan_out, 2),
                        "instability": round(m.instability, 3),
                        "god_module": m.file_path in god_paths,
                        "unstable": m.file_path in unstable_paths,
                    }
                    for m in modules
                ],
                "cycles": cycles,
                "god_modules": [m.file_path for m in gods],
                "sdp_violations": [_sdp_dict(v) for v in sdp],
            }
        )
        return

    if not modules:
        print("No data — run first: debtector index <directory>")
        return

    # Sort
    sort_key = getattr(args, "sort", "fan_in")
    modules_sorted = sorted(modules, key=lambda m: getattr(m, sort_key, 0), reverse=True)
    if args.limit:
        modules_sorted = modules_sorted[: args.limit]

    # Header
    col_w = max((len(m.file_path) for m in modules_sorted), default=30)
    col_w = max(col_w, 30)
    header = f"{'Module':<{col_w}}  {'Ca':>6}  {'Ce':>6}  {'I':>6}  {'Flags'}"
    print()
    print(header)
    print("─" * len(header))

    for m in modules_sorted:
        flags = ""
        if m.file_path in god_paths:
            flags += " ● god"
        if m.file_path in unstable_paths:
            flags += " ⚠ unstable"
        print(
            f"{m.file_path:<{col_w}}  {m.fan_in:>6.1f}  {m.fan_out:>6.1f}"
            f"  {m.instability:>6.3f}  {flags}"
        )

    print("─" * len(header))
    print(f"Total: {len(modules)} modules")

    # Cycles
    if cycles:
        print(f"\n⚠  Cycles detected ({len(cycles)}):")
        for cycle in cycles:
            print("   " + " → ".join(cycle) + " → ...")
    else:
        print("\n✓  No cycles")

    # God modules
    if gods:
        thr = cfg.metrics.thresholds
        print(
            f"\n● God modules (Ca > p{int(thr.god_module_percentile)} "
            f"and Ca >= {thr.god_module_min_ca:g}):"
        )
        for m in gods:
            print(f"   {m.file_path}  Ca={m.fan_in:.1f}")

    # SDP violations: a more stable module depends on a less stable one
    if sdp:
        print(f"\n⚠  SDP violations ({len(sdp)}):")
        for v in sdp:
            print(f"   {_sdp_text(_sdp_dict(v))}")


# Backward-compat alias — keeps existing imports and tests working
cmd_metrics = cmd_coupling


# ──────────────────────────────────────────────
# Git-coupling: behavioral analysis
# ──────────────────────────────────────────────


def cmd_hotspots(args) -> None:
    """Print hotspot ranking: files with high churn × cyclomatic complexity.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON.
            - ``limit`` (int | None): Max results.
            - ``since`` (str | None): Date filter (e.g. ``"6 months ago"``).
            - ``min_coupling`` (float): Minimum coupling to include. Default 0.
    """
    _auto_index(args.project)
    root = _index_root(args.project)
    store = _get_store(args.project)
    hotspots = compute_hotspots(
        store,
        root,
        since=getattr(args, "since", None),
        limit=getattr(args, "limit", None),
    )
    store.close()

    if args.json:
        _json_out(
            {
                "hotspots": [
                    {
                        "file_path": h.file_path,
                        "churn": h.churn,
                        "complexity": h.complexity,
                        "coupling": round(h.coupling, 2),
                        "hotspot_score": round(h.hotspot_score, 2),
                    }
                    for h in hotspots
                ]
            }
        )
        return

    if not hotspots:
        print("No hotspots — run first: debtector index <directory>")
        return

    col_w = max((len(h.file_path) for h in hotspots), default=30)
    col_w = max(col_w, 30)
    header = f"{'Module':<{col_w}}  {'Churn':>7}  {'Complexity':>10}  {'Coupling':>9}  {'Score':>8}"
    print()
    print(header)
    print("─" * len(header))
    for h in hotspots:
        print(
            f"{h.file_path:<{col_w}}  {h.churn:>7}  {h.complexity:>10}  {h.coupling:>9.2f}"
            f"  {h.hotspot_score:>8.2f}"
        )
    print("─" * len(header))
    print(f"Total: {len(hotspots)} hotspots")


def cmd_temporal_coupling(args) -> None:
    """Print pairs of files that frequently change together.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON.
            - ``limit`` (int | None): Max results.
            - ``since`` (str | None): Date filter.
            - ``min_shared`` (int): Minimum shared commits. Default 5.
            - ``min_ratio`` (float): Minimum coupling ratio. Default 0.3.
    """
    root = _index_root(args.project)
    pairs = compute_temporal_coupling(
        root,
        min_shared=getattr(args, "min_shared", 5),
        min_ratio=getattr(args, "min_ratio", 0.3),
        since=getattr(args, "since", None),
    )

    if args.json:
        _json_out(
            {
                "temporal_coupling": [
                    {
                        "file_a": t.file_a,
                        "file_b": t.file_b,
                        "shared_commits": t.shared_commits,
                        "coupling_ratio": round(t.coupling_ratio, 4),
                    }
                    for t in pairs
                ]
            }
        )
        return

    if not pairs:
        print("No temporal coupling detected")
        return

    col_w = max(
        (max(len(t.file_a), len(t.file_b)) for t in pairs),
        default=30,
    )
    col_w = max(col_w, 25)
    header = f"{'File A':<{col_w}}  {'File B':<{col_w}}  {'Commits':>7}  {'Ratio':>6}"
    print()
    print(header)
    print("─" * len(header))
    limit = getattr(args, "limit", None)
    shown = pairs[:limit] if limit else pairs
    for t in shown:
        print(
            f"{t.file_a:<{col_w}}  {t.file_b:<{col_w}}"
            f"  {t.shared_commits:>7}  {t.coupling_ratio:>6.3f}"
        )
    print("─" * len(header))
    print(f"Total: {len(pairs)} pares")


def cmd_bus_factor(args) -> None:
    """Print bus-factor risk per file (knowledge concentration).

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON.
            - ``limit`` (int | None): Max results.
    """
    _auto_index(args.project)
    root = _index_root(args.project)
    store = _get_store(args.project)
    results = compute_bus_factor(store, root)
    store.close()

    limit = getattr(args, "limit", None)
    if limit:
        results = results[:limit]

    if args.json:
        _json_out(
            {
                "bus_factor": [
                    {
                        "file_path": b.file_path,
                        "top_author": b.top_author,
                        "top_author_pct": round(b.top_author_pct, 1),
                        "bus_factor": b.bus_factor,
                    }
                    for b in results
                ]
            }
        )
        return

    if not results:
        print("No data — run first: debtector index <directory>")
        return

    col_w = max((len(b.file_path) for b in results), default=30)
    col_w = max(col_w, 30)
    aut_w = max((len(b.top_author) for b in results), default=15)
    aut_w = max(aut_w, 15)
    header = f"{'Module':<{col_w}}  {'Top author':<{aut_w}}  {'% lines':>9}  {'Bus factor':>10}"
    print()
    print(header)
    print("─" * len(header))
    for b in results:
        risk = " ⚠" if b.bus_factor == 1 else ""
        print(
            f"{b.file_path:<{col_w}}  {b.top_author:<{aut_w}}"
            f"  {b.top_author_pct:>8.1f}%  {b.bus_factor:>10}{risk}"
        )
    print("─" * len(header))
    print(f"Total: {len(results)} files analyzed")


def cmd_git_coupling(args) -> None:
    """Print all behavioral coupling metrics: hotspots, temporal coupling, bus factor.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON with keys hotspots, temporal_coupling, bus_factor.
            - ``limit`` (int | None): Applied to hotspots and bus factor.
            - ``since`` (str | None): Date filter for hotspots and temporal coupling.
            - ``min_shared`` (int): Min shared commits for temporal coupling.
            - ``min_ratio`` (float): Min ratio for temporal coupling.
    """
    _auto_index(args.project)
    root = _index_root(args.project)
    store = _get_store(args.project)
    hotspots = compute_hotspots(
        store,
        root,
        since=getattr(args, "since", None),
        limit=getattr(args, "limit", None),
    )
    temporal = compute_temporal_coupling(
        root,
        min_shared=getattr(args, "min_shared", 5),
        min_ratio=getattr(args, "min_ratio", 0.3),
        since=getattr(args, "since", None),
    )
    bus = compute_bus_factor(store, root)
    store.close()

    limit = getattr(args, "limit", None)
    if limit is not None:
        bus = bus[:limit]

    if args.json:
        _json_out(
            {
                "hotspots": [
                    {
                        "file_path": h.file_path,
                        "churn": h.churn,
                        "complexity": h.complexity,
                        "coupling": round(h.coupling, 2),
                        "hotspot_score": round(h.hotspot_score, 2),
                    }
                    for h in hotspots
                ],
                "temporal_coupling": [
                    {
                        "file_a": t.file_a,
                        "file_b": t.file_b,
                        "shared_commits": t.shared_commits,
                        "coupling_ratio": round(t.coupling_ratio, 4),
                    }
                    for t in temporal
                ],
                "bus_factor": [
                    {
                        "file_path": b.file_path,
                        "top_author": b.top_author,
                        "top_author_pct": round(b.top_author_pct, 1),
                        "bus_factor": b.bus_factor,
                    }
                    for b in bus
                ],
            }
        )
        return

    # Human output: print each section
    _print_section("Hotspots", "─")
    if hotspots:
        col_w = max((len(h.file_path) for h in hotspots), default=30)
        col_w = max(col_w, 30)
        for h in hotspots:
            print(
                f"  {h.file_path:<{col_w}}  churn={h.churn}  complexity={h.complexity}"
                f"  coupling={h.coupling:.2f}  score={h.hotspot_score:.2f}"
            )
    else:
        print("  (no data)")

    _print_section("Temporal coupling", "─")
    if temporal:
        for t in temporal:
            print(
                f"  {t.file_a}  ↔  {t.file_b}"
                f"  ({t.shared_commits} commits, ratio={t.coupling_ratio:.3f})"
            )
    else:
        print("  (no data)")

    _print_section("Bus factor", "─")
    if bus:
        for b in bus:
            risk = " ⚠" if b.bus_factor == 1 else ""
            print(
                f"  {b.file_path}  {b.top_author}"
                f" ({b.top_author_pct:.1f}%)  bf={b.bus_factor}{risk}"
            )
    else:
        print("  (no data)")


def cmd_report(args) -> None:
    """Print a full coupling report: structural (Ca/Ce/I) + behavioral (git).

    Args:
        args: Parsed argument namespace.  Accepts all flags from both
            ``coupling`` and ``git-coupling`` commands.
    """
    _auto_index(args.project)
    root = _index_root(args.project)

    # ── Structural coupling ──
    cfg = load_config(args.project)
    store = _get_store(args.project)
    modules = compute_metrics(store)
    cycles = find_cycles(store)
    gods = _configured_god_modules(store, cfg)
    god_paths = {m.file_path for m in gods}
    unstable_paths = {v.target for v in _configured_sdp_violations(store, cfg)}

    # ── Behavioral coupling ──
    hotspots = compute_hotspots(
        store,
        root,
        since=getattr(args, "since", None),
        limit=getattr(args, "limit", None),
    )
    temporal = compute_temporal_coupling(
        root,
        min_shared=getattr(args, "min_shared", 5),
        min_ratio=getattr(args, "min_ratio", 0.3),
        since=getattr(args, "since", None),
    )
    bus = compute_bus_factor(store, root)
    store.close()

    if args.json:
        flagged_modules = [
            m for m in modules if m.file_path in god_paths or m.file_path in unstable_paths
        ]
        _json_out(
            {
                "modules": [
                    {
                        "file_path": m.file_path,
                        "fan_in": round(m.fan_in, 2),
                        "fan_out": round(m.fan_out, 2),
                        "instability": round(m.instability, 3),
                        "god_module": m.file_path in god_paths,
                        "instability_flag": m.file_path in unstable_paths,
                    }
                    for m in flagged_modules
                ],
                "cycles": cycles,
                "god_modules": [m.file_path for m in gods],
                "hotspots": [
                    {
                        "file_path": h.file_path,
                        "churn": h.churn,
                        "complexity": h.complexity,
                        "coupling": round(h.coupling, 2),
                        "hotspot_score": round(h.hotspot_score, 2),
                    }
                    for h in hotspots
                    if h.hotspot_score > 0
                ],
                "temporal_coupling": [
                    {
                        "file_a": t.file_a,
                        "file_b": t.file_b,
                        "shared_commits": t.shared_commits,
                        "coupling_ratio": round(t.coupling_ratio, 4),
                    }
                    for t in temporal
                ],
                "bus_factor": [
                    {
                        "file_path": b.file_path,
                        "top_author": b.top_author,
                        "top_author_pct": round(b.top_author_pct, 1),
                        "bus_factor": b.bus_factor,
                    }
                    for b in bus
                    if b.bus_factor == 1
                ],
            }
        )
        return

    # Human output — only show items that signal a problem in each section

    # ── Structural coupling: only flagged modules ──
    _print_section("Structural coupling")
    flagged: list[tuple] = []
    for m in sorted(modules, key=lambda x: x.fan_in, reverse=True):
        flags = []
        if m.file_path in god_paths:
            flags.append("● god")
        if m.file_path in unstable_paths:
            flags.append("⚠ unstable")
        if flags:
            flagged.append((m, "  ".join(flags)))

    if cycles:
        print(f"  ✗ Cycles ({len(cycles)}):")
        for cycle in cycles:
            print("    " + " → ".join(cycle))
    if flagged:
        col_w = max((len(m.file_path) for m, _ in flagged), default=30)
        col_w = max(col_w, 30)
        for m, flags_str in flagged:
            print(
                f"  {m.file_path:<{col_w}}  Ca={m.fan_in:>5.1f}  Ce={m.fan_out:>5.1f}"
                f"  I={m.instability:.3f}  {flags_str}"
            )
    if not cycles and not flagged:
        print("  ✓ No issues")

    # ── Hotspots: files with score > 0 ──
    _print_section("Hotspots")
    active = [h for h in hotspots if h.hotspot_score > 0]
    if active:
        col_w = max((len(h.file_path) for h in active), default=30)
        col_w = max(col_w, 30)
        for h in active[:10]:
            print(
                f"  {h.file_path:<{col_w}}  churn={h.churn:>4}  complexity={h.complexity:>4}"
                f"  coupling={h.coupling:>6.1f}  score={h.hotspot_score:>8.1f}"
            )
    else:
        print("  ✓ No relevant hotspots")

    # ── Temporal coupling: all results already filtered by min_shared/min_ratio ──
    _print_section("Temporal coupling")
    if temporal:
        for t in temporal[:10]:
            print(
                f"  {t.file_a}  ↔  {t.file_b}"
                f"  ({t.shared_commits} commits, ratio={t.coupling_ratio:.2f})"
            )
    else:
        print("  ✓ No implicit temporal coupling")

    # ── Bus factor: only single-author files (bf == 1) ──
    _print_section("Bus factor")
    silos = [b for b in bus if b.bus_factor == 1]
    if silos:
        col_w = max((len(b.file_path) for b in silos), default=30)
        col_w = max(col_w, 30)
        for b in silos:
            print(f"  {b.file_path:<{col_w}}  {b.top_author} ({b.top_author_pct:.1f}%)  ⚠ bf=1")
    else:
        print("  ✓ No single-author files")


# Entry point
# ──────────────────────────────────────────────


def main() -> None:
    """Entry point for the ``debtector`` CLI.

    Parses arguments first, then configures structured logging so that the
    correct project path (and therefore log file location) is known.
    Dispatches to the appropriate sub-command handler and exits.
    Prints help and exits with status 0 if no sub-command is provided.
    """
    parser = argparse.ArgumentParser(
        prog="debtector",
        description="Debtector - Coupling guardrail for CI/PR",
    )
    parser.add_argument("--project", "-p", default=".", help="Path to the project")
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit compact JSON on stdout (for AI consumption)",
    )

    # Shared by every sub-parser so the options also work after the sub-command.
    # SUPPRESS keeps a value given before the sub-command from being overwritten.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", "-p", default=argparse.SUPPRESS, help="Path to the project")
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit compact JSON on stdout (for AI consumption)",
    )

    sub = parser.add_subparsers(dest="command")

    # index
    p_idx = sub.add_parser("index", parents=[common], help="Index a project")
    p_idx.add_argument("path", help="Path to the directory to index")

    # search
    p_search = sub.add_parser("search", parents=[common], help="Search symbols")
    p_search.add_argument("query", help="Text to search for")
    p_search.add_argument("--kind", "-k", help="Filter: Class, Function, Method")

    # summary
    p_sum = sub.add_parser("summary", parents=[common], help="Summarize a file")
    p_sum.add_argument("file", help="Relative path of the file")

    # impact
    p_imp = sub.add_parser("impact", parents=[common], help="Impact analysis")
    p_imp.add_argument("files", nargs="+", help="Changed files")
    p_imp.add_argument("--depth", "-d", type=int, default=2, help="Maximum depth")

    # imports
    p_imports = sub.add_parser("imports", parents=[common], help="Find imports of a module")
    p_imports.add_argument("module", help="Module to search for")

    # status
    sub.add_parser("status", parents=[common], help="Index statistics")

    # baseline
    p_baseline = sub.add_parser("baseline", parents=[common], help="Manage the metrics baseline")
    p_baseline_sub = p_baseline.add_subparsers(dest="baseline_cmd")
    p_baseline_sub.add_parser(
        "save", parents=[common], help="Save a metrics snapshot as the baseline"
    )
    p_status = p_baseline_sub.add_parser(
        "status", parents=[common], help="Compare current metrics with the baseline"
    )
    p_status.add_argument(
        "--reporter",
        choices=["github", "gitlab"],
        default=None,
        help="Formato CI: github (Annotations) o gitlab (section markers)",
    )

    # diff
    p_diff = sub.add_parser(
        "diff", parents=[common], help="Architectural diff between two indexes (base vs. PR)"
    )
    p_diff.add_argument("db_base", nargs="?", help="Index of the base branch")
    p_diff.add_argument("db_pr", nargs="?", help="Index of the PR")
    p_diff.add_argument(
        "--base",
        dest="base_ref",
        metavar="REF",
        help="Git ref to compare the current index against (indexed in a temporary worktree)",
    )
    p_diff.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format: text (default) or markdown (PR comment)",
    )

    # coupling (ex-metrics)
    p_coupling = sub.add_parser(
        "coupling",
        parents=[common],
        help="Structural coupling (Ca, Ce, I, cycles, god modules)",
    )
    p_coupling.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
        help="Sort column (default: fan_in)",
    )
    p_coupling.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Maximum number of rows to show",
    )

    # metrics — deprecated alias for coupling
    p_metrics_alias = sub.add_parser(
        "metrics",
        parents=[common],
        help="[DEPRECATED] Use 'coupling'. Structural coupling metrics.",
    )
    p_metrics_alias.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
    )
    p_metrics_alias.add_argument("--limit", "-l", type=int, default=None)

    # callers
    p_callers = sub.add_parser("callers", parents=[common], help="Who calls a symbol?")
    p_callers.add_argument("qualified_name", help="qualified_name of the symbol")

    # complexity
    p_cx = sub.add_parser(
        "complexity", parents=[common], help="Functions sorted by cyclomatic complexity"
    )
    p_cx.add_argument("--limit", "-l", type=int, default=None)
    p_cx.add_argument("--min", type=int, default=0, help="Minimum complexity to include")

    # untested
    p_untested = sub.add_parser(
        "untested", parents=[common], help="Symbols without tests (no COVERS edge)"
    )
    p_untested.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path or directory prefix to filter by (optional)",
    )

    # audit
    p_audit = sub.add_parser("audit", parents=[common], help="Audit view: phase 3 for deep review")
    p_audit.add_argument(
        "--top-n",
        type=int,
        default=10,
        dest="top_n",
        help="Show top N entries per section (default: 10)",
    )
    p_audit.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Show all entries (do not limit by --top-n)",
    )

    # hotspots
    p_hotspots = sub.add_parser(
        "hotspots", parents=[common], help="Hotspots: churn × cyclomatic complexity"
    )
    p_hotspots.add_argument("--limit", "-l", type=int, default=None)
    p_hotspots.add_argument("--since", default=None, help="Date filter (e.g. '6 months ago')")
    p_hotspots.add_argument("--min-coupling", type=float, default=0.0, dest="min_coupling")

    # temporal-coupling
    p_tc = sub.add_parser(
        "temporal-coupling", parents=[common], help="Files that frequently change together"
    )
    p_tc.add_argument("--limit", "-l", type=int, default=None)
    p_tc.add_argument("--since", default=None)
    p_tc.add_argument("--min-shared", type=int, default=5, dest="min_shared")
    p_tc.add_argument("--min-ratio", type=float, default=0.3, dest="min_ratio")

    # bus-factor
    p_bus = sub.add_parser("bus-factor", parents=[common], help="Single-author risk per file")
    p_bus.add_argument("--limit", "-l", type=int, default=None)

    # git-coupling
    p_git = sub.add_parser(
        "git-coupling",
        parents=[common],
        help="Full behavioral analysis: hotspots + temporal + bus factor",
    )
    p_git.add_argument("--limit", "-l", type=int, default=None)
    p_git.add_argument("--since", default=None)
    p_git.add_argument("--min-shared", type=int, default=5, dest="min_shared")
    p_git.add_argument("--min-ratio", type=float, default=0.3, dest="min_ratio")

    # report
    p_report = sub.add_parser(
        "report", parents=[common], help="Full report: structural + behavioral coupling"
    )
    p_report.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
    )
    p_report.add_argument("--limit", "-l", type=int, default=None)
    p_report.add_argument("--since", default=None)
    p_report.add_argument("--min-shared", type=int, default=5, dest="min_shared")
    p_report.add_argument("--min-ratio", type=float, default=0.3, dest="min_ratio")

    args = parser.parse_args()

    # Configure logging after parsing so the project path is known
    configure_logging(project=args.project)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    cmds = {
        "index": cmd_index,
        "search": cmd_search,
        "summary": cmd_summary,
        "impact": cmd_impact,
        "imports": cmd_imports,
        "status": cmd_status,
        "coupling": cmd_coupling,
        "metrics": cmd_coupling,  # deprecated alias
        "baseline": cmd_baseline,
        "diff": cmd_diff,
        "callers": cmd_callers,
        "complexity": cmd_complexity,
        "untested": cmd_untested,
        "audit": cmd_audit,
        "hotspots": cmd_hotspots,
        "temporal-coupling": cmd_temporal_coupling,
        "bus-factor": cmd_bus_factor,
        "git-coupling": cmd_git_coupling,
        "report": cmd_report,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
