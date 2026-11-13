"""Git history commands: hotspots, temporal coupling, bus factor and git-coupling."""

from __future__ import annotations

import structlog

from ..git_history import compute_bus_factor, compute_hotspots, compute_temporal_coupling
from .common import _auto_index, _get_store, _index_root, _json_out, _print_section

log = structlog.get_logger()


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
