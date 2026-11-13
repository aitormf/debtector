"""Baseline command: save and compare coupling metrics (ratcheting)."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from .. import metrics as _metrics
from ..config import Severity, load_config
from ..diff import _function_complexity, instability_grew
from ..metrics import compute_metrics, find_cycles
from .common import (
    _blocks,
    _configured_god_modules,
    _configured_sdp_violations,
    _get_store,
    _json_out,
    _sdp_dict,
    _warns,
)
from .reporters import _complexity_text, _emit_github_annotations, _emit_gitlab_report, _sdp_text

_BASELINE_FILE = ".debtector/baseline.json"


def _baseline_path(project: str) -> Path:
    return Path(project) / _BASELINE_FILE


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
    medium = cfg.audit.complexity_medium
    functions = {qn: cx for qn, (cx, _) in _function_complexity(store).items() if cx >= medium}
    store.close()

    snapshot = {
        "metrics_version": _metrics.METRICS_VERSION,
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
        "complexity": {"medium": medium, "functions": functions},
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

    Each issue type (cycles, god_modules, instability, complexity) is filtered through the
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
    current_complexity = _function_complexity(store)
    store.close()

    # A baseline from another metric version has incomparable Ca/Ce (D-0014); the
    # ones saved before the field existed are version 1. Cycles do not depend on them.
    saved_version = baseline.get("metrics_version", 1)
    mismatch = saved_version != _metrics.METRICS_VERSION
    if mismatch:
        current_gods, current_sdp, current_modules = [], [], []

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

    # Complexity (D-0010): new or worse functions at or above the threshold. A baseline
    # without it, or saved with another threshold, is not comparable (D-0019).
    complexity_regs: list[dict] = []
    complexity_skipped = None
    saved_cx = baseline.get("complexity")
    medium = cfg.audit.complexity_medium
    if saved_cx is None:
        complexity_skipped = "baseline has no complexity"
    elif saved_cx.get("medium") != medium:
        complexity_skipped = f"baseline saved with complexity_medium {saved_cx.get('medium')}"
    else:
        known_cx = saved_cx.get("functions", {})
        complexity_regs = [
            {"qualified_name": qn, "file_path": path, "before": known_cx.get(qn), "after": cx}
            for qn, (cx, path) in current_complexity.items()
            if cx >= medium and (qn not in known_cx or cx > known_cx[qn])
        ]

    # Decide whether each regression type blocks CI according to its severity
    has_blocking = (
        _blocks(new_cycles, sev.cycles)
        or _blocks(new_gods, sev.god_modules)
        or _blocks(regressions, sev.instability)
        or _blocks(new_sdp, sev.instability)
        or _blocks(complexity_regs, sev.complexity)
    )

    if args.json:
        result = {
            "regressions": regressions,
            "new_cycles": new_cycles,
            "new_god_modules": new_gods,
            "new_sdp_violations": new_sdp,
            "complexity_regressions": complexity_regs,
        }
        if complexity_skipped:
            result["complexity_skipped"] = complexity_skipped
        if mismatch:
            result["metrics_version_mismatch"] = {
                "baseline": saved_version,
                "current": _metrics.METRICS_VERSION,
            }
        _json_out(result)
        if has_blocking:
            sys.exit(1)
        return

    has_any_warning = (
        _warns(new_cycles, sev.cycles)
        or _warns(new_gods, sev.god_modules)
        or _warns(regressions, sev.instability)
        or _warns(new_sdp, sev.instability)
        or _warns(complexity_regs, sev.complexity)
    )

    reporter = getattr(args, "reporter", None)

    if mismatch:
        print(
            f"⚠  baseline saved with coupling metrics v{saved_version}, current is "
            f"v{_metrics.METRICS_VERSION}: run debtector baseline save"
        )

    if complexity_skipped:
        print(f"⚠  complexity not compared ({complexity_skipped}): run debtector baseline save")

    if not has_any_warning:
        print("✓  No changes from baseline")
        return

    if reporter == "github":
        _emit_github_annotations(new_cycles, new_gods, regressions, sev, new_sdp, complexity_regs)
    elif reporter == "gitlab":
        _emit_gitlab_report(new_cycles, new_gods, regressions, sev, new_sdp, complexity_regs)
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

        if _warns(complexity_regs, sev.complexity):
            label = "⛔" if sev.complexity == Severity.ERROR else "⚠"
            print(f"\n{label}  Complexity regressions ({len(complexity_regs)}):")
            for c in complexity_regs:
                print(f"   {_complexity_text(c)}")

    if has_blocking:
        sys.exit(1)
