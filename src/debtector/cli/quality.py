"""Quality commands: complexity, untested, audit."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import structlog

from ..audit import (
    CohesionFinding,
    compute_health_score,
    compute_lcom4,
    critical_knowledge_concentration,
    prioritize_cycles,
    select_actionable_hotspots,
    untested_high_coupling,
    untested_hotspots,
)
from ..audit.complexity import ComplexityFinding, select_complexity_findings
from ..config import AuditThresholds, load_config
from ..git_history import (
    compute_bus_factor,
    compute_hotspots,
    is_shallow_repository,
    list_authors,
    parse_churn,
)
from ..graph_store import GraphStore
from ..metrics import compute_metrics, find_cycles, inheritance_metrics
from ..models import NodeKind, node_to_dict
from .common import _auto_index, _configured_god_modules, _get_store, _index_root, _json_out

log = structlog.get_logger()


def cmd_complexity(args) -> None:
    """Print functions and methods sorted by cyclomatic complexity, highest first.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON instead of human-readable text.
            - ``limit`` (int | None): Maximum number of results.
            - ``min`` (int): Only include complexity at or above this value.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    nodes = store.get_nodes_by_kind(NodeKind.FUNCTION) + store.get_nodes_by_kind(NodeKind.METHOD)
    store.close()

    min_value = getattr(args, "min", 0) or 0
    rows = [
        (n, int(n.extra["complexity"]))
        for n in nodes
        if "complexity" in n.extra and int(n.extra["complexity"]) >= min_value
    ]
    rows.sort(key=lambda r: (-r[1], r[0].qualified_name))
    limit = getattr(args, "limit", None)
    if limit is not None:
        rows = rows[:limit]

    if args.json:
        _json_out(
            {
                "functions": [
                    {
                        "qualified_name": n.qualified_name,
                        "kind": n.kind,
                        "complexity": value,
                        "file_path": n.file_path,
                        "line": n.line_start,
                    }
                    for n, value in rows
                ]
            }
        )
        return

    if not rows:
        print("No functions with complexity data — run first: debtector index <directory>")
        return
    print("\nCyclomatic complexity")
    print("─" * 60)
    for n, value in rows:
        print(f"  {value:>4}  {n.qualified_name}")
        print(f"        {n.file_path}:{n.line_start}")
    print(f"\nTotal: {len(rows)}")


def cmd_untested(args) -> None:
    """List production symbols (Function/Method) that have no COVERS edge.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``path`` (str | None): Optional file or directory prefix to filter results.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    symbols = store.get_uncovered_symbols(path_filter=args.path or None)
    store.close()

    if args.json:
        _json_out([node_to_dict(n) for n in symbols])
    else:
        if not symbols:
            print("✓ All symbols are covered.")
            return
        print(f"\nUntested symbols ({len(symbols)}):")
        print("─" * 60)
        for n in symbols:
            print(f"  {n.kind:10s} {n.name}")
            print(f"             {n.file_path}:{n.line_start}")


def _get_uncovered_files(store: GraphStore) -> set[str]:
    """Get production files where no function or method has a COVERS edge."""
    return store.get_untested_files()


# Meaning of summary.health_score: 2 = normalised by size, actionable hotspots only;
# 3 = hotspots ranked by churn x cyclomatic complexity (was churn x coupling);
# 4 = production functions with high cyclomatic complexity are scored findings;
# 5 = a hotspot is high from hotspot_high_factor x the actionable cut, medium below.
_HEALTH_SCORE_VERSION = 5


def _complexity_findings(store: GraphStore, thr: AuditThresholds) -> list[ComplexityFinding]:
    """Return the scored function-complexity findings of the index (D-0006).

    Args:
        store: Open graph store.
        thr: Audit thresholds (``complexity_medium`` / ``complexity_high``).

    Returns:
        Findings for production functions and methods, most complex first.
    """
    nodes = store.get_nodes_by_kind(NodeKind.FUNCTION) + store.get_nodes_by_kind(NodeKind.METHOD)
    return select_complexity_findings(
        nodes,
        medium=thr.complexity_medium,
        high=thr.complexity_high,
        is_test=store.is_test_path,
    )


def _single_author(root: str | Path) -> bool:
    """Return True when the whole commit history has exactly one author.

    Args:
        root: Directory the audit's history commands run in.

    Returns:
        ``False`` when there are several authors or the history is unavailable.
    """
    try:
        if is_shallow_repository(root):
            # A shallow clone (CI default) shows only recent commits: unknown, not single.
            log.warning("authors_unknown_shallow_clone", root=str(root))
            return False
        return len(list_authors(root)) == 1
    except RuntimeError:
        log.warning("authors_unavailable", root=str(root), exc_info=True)
        return False


def cmd_audit(args) -> None:
    """Audit surface: second presenter for tech lead review.

    Eight sections: summary, coupling, cycles, cohesion, testRisk, hotspots,
    busFactor, inheritance. Respects --top-n (default 10) and --full.
    Outputs schema v1 JSON with --json.

    Args:
        args: Parsed argument namespace with project, top_n, full, json flags.
    """
    _auto_index(args.project)
    root = _index_root(args.project)
    store = _get_store(args.project)
    cfg = load_config(args.project)
    thr = cfg.audit

    # Compute core metrics
    module_metrics = compute_metrics(store)
    cycles = find_cycles(store)
    hotspots = compute_hotspots(store, root)
    bus_factor = compute_bus_factor(store, root)
    inheritance = [i for i in inheritance_metrics(store) if not i.qualified_name.startswith("../")]
    churn = parse_churn(root)

    # testRisk: without tests every file looks "uncovered", so the untested
    # joins would be noise; skip them (and keep the knowledge join).
    tests_found = store.count_test_files() > 0
    tr_findings = critical_knowledge_concentration(
        bus_factor, module_metrics, ca_threshold=thr.testrisk_high_ca
    )
    if tests_found:
        uncovered_files = _get_uncovered_files(store)
        tr_findings = (
            untested_high_coupling(
                uncovered_files, module_metrics, ce_threshold=thr.testrisk_high_ce
            )
            + untested_hotspots(uncovered_files, churn, churn_threshold=thr.testrisk_high_churn)
            + tr_findings
        )
    else:
        log.warning("testrisk_skipped", reason="no_tests_found", project=args.project)

    # Compute LCOM4 for each class
    cohesion = []
    for c in store.get_nodes_by_kind(NodeKind.CLASS):
        if c.file_path.startswith("../"):  # tests added via test_paths
            continue
        lcom4 = compute_lcom4(store, c.qualified_name)
        cohesion.append(
            CohesionFinding(
                qualified_name=c.qualified_name,
                lcom4=lcom4,
                methods_count=len(
                    [e for e in store.get_outgoing(c.qualified_name) if e.kind == "HAS_METHOD"]
                ),
                candidate_to_split=lcom4 > 1,
            )
        )
    # Cohesion is informational for now: LCOM4 only links methods through CALLS,
    # not shared attributes, so most cohesive classes look like split candidates.

    # Health score and stats before closing store
    stats = store.get_stats()
    # Tests added via test_paths (outside the index root) are not modules/classes.
    n_modules = stats.files_count - store.count_external_nodes(NodeKind.FILE)
    # With a single author in the whole history, bus factor 1 says nothing.
    scored_findings = list(tr_findings)
    if _single_author(root):
        scored_findings = [
            f for f in scored_findings if f.label != "critical knowledge concentration"
        ]
    actionable_hotspots = select_actionable_hotspots(
        hotspots,
        percentile=thr.hotspot_percentile,
        min_score=thr.hotspot_min_score,
        high_factor=thr.hotspot_high_factor,
    )
    scored_findings += actionable_hotspots
    hotspot_severity = {h.file_path: h.severity for h in actionable_hotspots}
    complexity_findings = _complexity_findings(store, thr)
    health = compute_health_score(scored_findings + complexity_findings, modules=n_modules)
    n_classes = stats.nodes_by_kind.get(NodeKind.CLASS, 0) - store.count_external_nodes(
        NodeKind.CLASS
    )

    # Prioritize cycles and detect god modules before closing store
    prioritized_cycles = prioritize_cycles(store)
    god_modules_set = _configured_god_modules(store, cfg)

    # Close store after all reads
    store.close()

    # Format output
    top_n = args.top_n if not args.full else None

    def limit(lst):
        return lst if top_n is None else lst[:top_n]

    if args.json:
        # Format cycles
        cycles_out = [
            {
                "nodes": c.cycle,
                "pivot": c.pivot,
                "pivot_ca": c.max_fan_in,
                "rationale": "break first" if i == 0 else "follow-up",
            }
            for i, c in enumerate(limit(prioritized_cycles))
        ]
        output = {
            "schema_version": 1,
            "summary": {
                "modules": n_modules,
                "cycles": len(cycles),
                "classes": n_classes,
                "health_score": health.score,
                "health_score_version": _HEALTH_SCORE_VERSION,
            },
            "coupling": limit(
                [
                    {
                        "file_path": m.file_path,
                        "fan_in": round(m.fan_in, 2),
                        "fan_out": round(m.fan_out, 2),
                        "instability": round(m.instability, 3),
                        "god_module": m in god_modules_set,
                    }
                    for m in sorted(module_metrics, key=lambda x: x.fan_in, reverse=True)
                ]
            ),
            "cycles": cycles_out,
            "cohesion": limit(
                [
                    {
                        "qualified_name": x.qualified_name,
                        "lcom4": round(x.lcom4, 2),
                        "methods_count": x.methods_count,
                        "candidate_to_split": x.candidate_to_split,
                    }
                    for x in sorted(cohesion, key=lambda x: x.lcom4, reverse=True)
                    if x.lcom4 > 0
                ]
            ),
            "testRisk": {
                **(
                    {"status": "ok"}
                    if tests_found
                    else {"status": "skipped", "reason": "no_tests_found"}
                ),
                "untested_high_coupling": [
                    f.file_path for f in tr_findings if f.label == "untested high-coupling"
                ],
                "untested_hotspots": [
                    f.file_path for f in tr_findings if f.label == "untested hotspots"
                ],
                "critical_knowledge_concentration": [
                    f.file_path
                    for f in tr_findings
                    if f.label == "critical knowledge concentration"
                ],
            },
            "hotspots": limit(
                [
                    {
                        "file_path": h.file_path,
                        "churn": h.churn,
                        "complexity": h.complexity,
                        "score": round(h.hotspot_score, 1),
                        "severity": hotspot_severity.get(h.file_path),
                    }
                    for h in sorted(hotspots, key=lambda x: x.hotspot_score, reverse=True)
                    if h.hotspot_score > 0
                ]
            ),
            "busFactor": limit(
                [
                    {
                        "file_path": b.file_path,
                        "top_author": b.top_author,
                        "bus_factor": b.bus_factor,
                    }
                    for b in bus_factor
                    if b.bus_factor == 1
                ]
            ),
            "inheritance": limit(
                [
                    {"qualified_name": i.qualified_name, "depth": i.depth, "children": i.children}
                    for i in sorted(inheritance, key=lambda x: x.depth, reverse=True)
                    if i.depth > 0 or i.children > 0
                ]
            ),
            "complexity": limit([asdict(f) for f in complexity_findings]),
        }
        _json_out(output)
    else:
        print(f"\n┌─ Audit Summary (health: {health.score}/100)")
        print(f"│  modules={n_modules}  cycles={len(cycles)}")
        print(f"│  critical={health.counts.critical}  high={health.counts.high}")
        print("└─\n")
        for h in limit(sorted(actionable_hotspots, key=lambda x: x.hotspot_score, reverse=True)):
            print(f"hotspot {h.severity}: {h.file_path} ({round(h.hotspot_score, 1)})")
        for f in limit(complexity_findings):
            print(f"complexity {f.severity}: {f.qualified_name} ({f.complexity})")
        if not tests_found:
            print(
                "No tests found; testRisk disabled. Configure `test_paths` in `debtector.toml`.",
                file=sys.stderr,
            )
