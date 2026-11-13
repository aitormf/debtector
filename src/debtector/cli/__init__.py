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
import sys

import structlog

from ..config import load_config
from ..git_history import (
    compute_bus_factor,
    compute_hotspots,
    compute_temporal_coupling,
)
from ..logging import configure_logging
from ..metrics import (
    compute_metrics,
    find_cycles,
)
from .baseline import cmd_baseline
from .common import (
    _auto_index,
    _configured_god_modules,
    _configured_sdp_violations,
    _get_store,
    _index_root,
    _json_out,
    _print_section,
)
from .coupling import cmd_coupling
from .graph import (
    cmd_callers,
    cmd_impact,
    cmd_imports,
    cmd_index,
    cmd_search,
    cmd_status,
    cmd_summary,
)
from .pr_diff import cmd_diff
from .quality import cmd_audit, cmd_complexity, cmd_untested

log = structlog.get_logger()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────

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
