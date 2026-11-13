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

from ..logging import configure_logging
from .baseline import cmd_baseline
from .coupling import cmd_coupling
from .git import cmd_bus_factor, cmd_git_coupling, cmd_hotspots, cmd_temporal_coupling
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
from .report import cmd_report

log = structlog.get_logger()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────


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
