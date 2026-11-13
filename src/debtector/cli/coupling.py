"""Coupling command: structural coupling metrics (Ca, Ce, I, cycles, god modules)."""

from __future__ import annotations

import structlog

from ..config import load_config
from ..metrics import compute_metrics, find_cycles
from .common import (
    _auto_index,
    _configured_god_modules,
    _configured_sdp_violations,
    _get_store,
    _json_out,
    _sdp_dict,
)
from .reporters import _sdp_text

log = structlog.get_logger()


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
