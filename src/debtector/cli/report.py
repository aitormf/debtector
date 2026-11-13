"""Combined report command: structural coupling plus git-history coupling."""

from __future__ import annotations

from ..config import load_config
from ..git_history import compute_bus_factor, compute_hotspots, compute_temporal_coupling
from ..metrics import compute_metrics, find_cycles
from .common import (
    _auto_index,
    _configured_god_modules,
    _configured_sdp_violations,
    _get_store,
    _index_root,
    _json_out,
    _print_section,
)


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
