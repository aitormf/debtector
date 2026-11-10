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
import sys
import time
from dataclasses import asdict
from pathlib import Path

import structlog

from .audit import (
    CohesionFinding,
    compute_health_score,
    compute_lcom4,
    critical_knowledge_concentration,
    prioritize_cycles,
    select_actionable_hotspots,
    untested_high_coupling,
    untested_hotspots,
)
from .audit.complexity import ComplexityFinding, select_complexity_findings
from .config import AuditThresholds, Severity, load_config
from .git_history import (
    compute_bus_factor,
    compute_hotspots,
    compute_temporal_coupling,
    is_shallow_repository,
    list_authors,
    parse_churn,
)
from .graph_store import GraphStore
from .indexer import Indexer
from .logging import configure_logging
from .metrics import (
    compute_metrics,
    find_cycles,
    god_modules,
    inheritance_metrics,
    sdp_violations,
)
from .models import NodeKind, node_to_dict

log = structlog.get_logger()

# Metadata key: indexed directory, relative to the project root (portable if
# index.db is committed).
_INDEX_ROOT_KEY = "index_root"

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _debtector_dir(project: str) -> Path:
    """Return the ``.debtector/`` directory for *project*, creating it if needed.

    Args:
        project: Path to the project root.

    Returns:
        A :class:`~pathlib.Path` pointing to ``{project}/.debtector/``.
    """
    d = Path(project) / ".debtector"
    d.mkdir(parents=True, exist_ok=True)
    gitignore = d / ".gitignore"
    gitignore.write_text(
        "# Managed by debtector — do not edit manually\n*\n!.gitignore\n!baseline.json\n",
        encoding="utf-8",
    )
    return d


def _auto_index(project: str) -> None:
    """Index the project silently before running analysis commands.

    Uses SHA-256 change detection: if no files have changed since the last
    index run, this is effectively a no-op.  All output goes to the log file;
    nothing is printed to stdout.

    Re-indexes the directory recorded by the last ``debtector index``. An
    index from an older version, with no recorded root, is left as is.

    Args:
        project: Path to the project root directory.
    """
    try:
        store = _get_store(project)
        try:
            rel = store.get_metadata(_INDEX_ROOT_KEY)
            if rel is None and store.get_all_files():
                # Index from before index_root was stored: its root is unknown,
                # and re-indexing from the project root would rewrite every path.
                log.info("auto_index_skipped_unknown_root", project=project)
                return
            Indexer(store).index(
                str(Path(project) / rel) if rel else project,
                extra_paths=_test_dirs(project),
            )
        finally:
            store.close()
    except Exception:  # noqa: BLE001
        # Never let a failed auto-index abort the analysis command that called it.
        log.warning("auto_index_failed", project=project, exc_info=True)


def _configured_god_modules(store: GraphStore, cfg) -> list:
    """God modules using the percentile and minimum Ca from ``debtector.toml``."""
    thr = cfg.metrics.thresholds
    return god_modules(store, percentile=thr.god_module_percentile, min_ca=thr.god_module_min_ca)


def _configured_sdp_violations(store: GraphStore, cfg) -> list:
    """SDP violations using ``sdp_margin`` from ``debtector.toml``."""
    return sdp_violations(store, margin=cfg.metrics.thresholds.sdp_margin)


def _sdp_dict(v) -> dict:
    """JSON-friendly form of an :class:`~debtector.metrics.SdpViolation`."""
    return {
        "source": v.source,
        "target": v.target,
        "source_instability": round(v.source_instability, 3),
        "target_instability": round(v.target_instability, 3),
    }


def _get_store(project: str) -> GraphStore:
    """Open the :class:`~debtector.graph_store.GraphStore` for *project*.

    The SQLite database lives at ``{project}/.debtector/index.db``.

    Args:
        project: Path to the project root directory.

    Returns:
        An open :class:`~debtector.graph_store.GraphStore` instance.
    """
    db_path = _debtector_dir(project) / "index.db"
    store = GraphStore(str(db_path))
    rel = store.get_metadata(_INDEX_ROOT_KEY)
    store.test_prefixes = _test_prefixes(project, str(Path(project) / rel) if rel else project)
    return store


def _test_dirs(project: str) -> list[str]:
    """Return the absolute ``test_paths`` of ``debtector.toml``.

    A config that cannot be loaded yields no extra paths (logged, not fatal):
    analysis commands must keep working with the conventions alone.

    Args:
        project: Path to the project root (where ``debtector.toml`` lives).

    Returns:
        Absolute paths, one per entry in ``test_paths``.
    """
    try:
        cfg = load_config(project)
    except ValueError:
        log.warning("test_paths_config_invalid", project=project, exc_info=True)
        return []
    return [os.path.abspath(Path(project) / p) for p in cfg.test_paths]


def _test_prefixes(project: str, index_root: str) -> list[str]:
    """Return the ``test_paths`` as path prefixes relative to the index root.

    Args:
        project: Path to the project root.
        index_root: Directory the graph's paths are relative to.

    Returns:
        Prefixes with a trailing ``/`` (``""`` for the index root itself),
        matching how file paths are stored in the graph.
    """
    prefixes = []
    for d in _test_dirs(project):
        rel = Path(os.path.relpath(d, os.path.abspath(index_root))).as_posix()
        prefixes.append("" if rel == "." else rel + "/")
    return prefixes


def _index_root(project: str) -> str:
    """Return the directory last indexed for *project*.

    Paths in the graph are relative to it, so auto-index and git (churn,
    temporal coupling, blame) must run from it, not from the project root.

    Args:
        project: Path to the project root directory.

    Returns:
        The indexed directory, or *project* if it has never been indexed.
    """
    store = _get_store(project)
    try:
        rel = store.get_metadata(_INDEX_ROOT_KEY)
    finally:
        store.close()
    return str(Path(project) / rel) if rel else project


def _json_out(data) -> None:
    """Print *data* as compact JSON to stdout.

    Args:
        data: Any JSON-serialisable object.
    """
    print(json.dumps(data, default=str))


# ──────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────


def cmd_index(args) -> None:
    """Run the indexer on a project directory and print a summary.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Root directory where ``.debtector/`` is stored.
            - ``path`` (str): Directory tree to scan and index.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    store = _get_store(args.project)
    indexer = Indexer(store)

    if not args.json:
        print(f"Indexing {args.path}...")

    # Prefixes must be relative to the directory being indexed now, not the stored root.
    store.test_prefixes = _test_prefixes(args.project, args.path)
    stats = indexer.index(args.path, extra_paths=_test_dirs(args.project))
    rel_root = Path(os.path.relpath(Path(args.path).resolve(), Path(args.project).resolve()))
    store.set_metadata(_INDEX_ROOT_KEY, rel_root.as_posix())
    store.close()

    if args.json:
        _json_out(stats)
    else:
        print(f"\n  Files scanned:      {stats['scanned']}")
        print(f"  Indexed:            {stats['indexed']}")
        print(f"  Unchanged:          {stats['skipped']}")
        print(f"  Errors:             {stats['errors']}")
        print(f"  Deleted:            {stats['removed']}")


def cmd_search(args) -> None:
    """Search the index for symbols matching a query and print results.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``query`` (str): Free-text search query.
            - ``kind`` (str | None): Optional node kind filter (e.g. ``"Class"``).
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    store = _get_store(args.project)
    results = store.search_nodes(args.query, kind=args.kind)
    store.close()

    if args.json:
        _json_out([node_to_dict(n) for n in results])
    else:
        print(f"\nResults for: '{args.query}'")
        print("─" * 60)
        for n in results:
            print(f"  {n.kind:10s} {n.qualified_name}")
            if n.signature:
                print(f"             {n.signature}")
            print()
        print(f"Total: {len(results)}")


def cmd_summary(args) -> None:
    """Print a structural summary (symbols and edges) for a single file.

    Exits with status 1 if the file is not found in the index.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``file`` (str): Relative path of the file to summarise.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    summary = store.get_file_summary(args.file)
    store.close()

    if not summary:
        if args.json:
            _json_out({"error": f"file not found: {args.file}"})
        else:
            print(f"File not found: {args.file}")
        sys.exit(1)

    if args.json:
        _json_out(summary)
    else:
        print(f"\n{summary['path']} ({summary['language']})")
        print("─" * 60)
        if summary["nodes"]:
            print("\n  Symbols:")
            for s in summary["nodes"]:
                parent = "  └─ " if s["parent"] else "  "
                print(f"    {parent}{s['kind']:10s} {s.get('signature') or s['name']}")
        if summary["edges"]:
            print("\n  Relationships:")
            for e in summary["edges"]:
                print(f"    {e['kind']:15s} {e['source']} → {e['target']}")


def cmd_impact(args) -> None:
    """Perform an impact-radius analysis and print affected files and nodes.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``files`` (list[str]): List of changed file paths (seeds).
            - ``depth`` (int): Maximum traversal depth.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    result = store.get_impact_radius(args.files, max_depth=args.depth)
    store.close()

    if args.json:
        _json_out(
            {
                "changed_nodes": [n.qualified_name for n in result["changed_nodes"]],
                "impacted_nodes": [node_to_dict(n) for n in result["impacted_nodes"]],
                "impacted_files": sorted(result["impacted_files"]),
            }
        )
    else:
        print(f"\nImpact analysis (depth {args.depth}):")
        print("─" * 60)
        print(f"\n  Changed nodes:    {len(result['changed_nodes'])}")
        print(f"  Impacted nodes:   {len(result['impacted_nodes'])}")
        print(f"  Affected files:   {len(result['impacted_files'])}")
        if result["impacted_files"]:
            print("\n  Impacted files:")
            for f in sorted(result["impacted_files"]):
                print(f"    {f}")
        if result["impacted_nodes"]:
            print("\n  Impacted nodes:")
            for n in result["impacted_nodes"][:20]:
                print(f"    {n.kind:10s} {n.qualified_name}")
            if len(result["impacted_nodes"]) > 20:
                print(f"    ... and {len(result['impacted_nodes']) - 20} more")


def cmd_imports(args) -> None:
    """Search for files that import a given module and print results.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``module`` (str): Module name substring to search for.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    results = store.search_imports(args.module)
    store.close()

    if args.json:
        _json_out(results)
    else:
        print(f"\nFiles importing '{args.module}':")
        print("─" * 60)
        for r in results:
            print(f"  {r['file_path']}  (line {r['line']})")
        print(f"\nTotal: {len(results)}")


def cmd_status(args) -> None:
    """Print index statistics (file count, node/edge counts, breakdown by kind).

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    store = _get_store(args.project)
    stats = store.get_stats()
    store.close()

    if args.json:
        _json_out(
            {
                "files": stats.files_count,
                "total_nodes": stats.total_nodes,
                "total_edges": stats.total_edges,
                "languages": stats.languages,
                "nodes_by_kind": stats.nodes_by_kind,
                "edges_by_kind": stats.edges_by_kind,
            }
        )
    else:
        print("\nIndex status:")
        print("─" * 40)
        print(f"  Files:       {stats.files_count}")
        print(f"  Nodes:       {stats.total_nodes}")
        print(f"  Edges:       {stats.total_edges}")
        print(f"  Languages:   {', '.join(stats.languages)}")
        if stats.nodes_by_kind:
            print("\n  Nodes by kind:")
            for k, v in stats.nodes_by_kind.items():
                print(f"    {k:12s} {v}")
        if stats.edges_by_kind:
            print("\n  Edges by kind:")
            for k, v in stats.edges_by_kind.items():
                print(f"    {k:15s} {v}")


def cmd_callers(args) -> None:
    """Print all callers of a given symbol (by qualified name).

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``qualified_name`` (str): The qualified name of the target symbol.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    callers = store.callers_of(args.qualified_name)
    store.close()

    if args.json:
        _json_out([node_to_dict(n) for n in callers])
    else:
        print(f"\nWho calls {args.qualified_name}?")
        print("─" * 60)
        for n in callers:
            print(f"  {n.kind:10s} {n.qualified_name}")
            print(f"             {n.file_path}:{n.line_start}")
        print(f"\nTotal: {len(callers)}")


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


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# Baseline
# ──────────────────────────────────────────────

_BASELINE_FILE = ".debtector/baseline.json"
# Instability tolerance: minimum difference to count as a regression.
# A delta < 5% is treated as rounding noise, not real degradation.
_INSTABILITY_TOLERANCE = 0.05


def _baseline_path(project: str) -> Path:
    return Path(project) / _BASELINE_FILE


def _blocks(issues: list, severity: Severity) -> bool:
    """Return True if *issues* are non-empty and *severity* is ERROR."""
    return bool(issues) and severity == Severity.ERROR


def _warns(issues: list, severity: Severity) -> bool:
    """Return True if *issues* are non-empty and *severity* is ERROR or WARNING."""
    return bool(issues) and severity in (Severity.ERROR, Severity.WARNING)


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
        if m.instability > prev["instability"] + _INSTABILITY_TOLERANCE:
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


def _sdp_text(v: dict) -> str:
    """One-line description of an SDP violation dict (see :func:`_sdp_dict`)."""
    return (
        f"{v['source']} (I={v['source_instability']:.3f}) → "
        f"{v['target']} (I={v['target_instability']:.3f})"
    )


def _annotation_level(severity: Severity) -> str:
    """Map a :class:`Severity` to its GitHub Annotation level string."""
    return "error" if severity == Severity.ERROR else "warning"


def _safe_annotation_path(path: str) -> str:
    """Sanitize a file path for use in a GitHub Actions annotation.

    GitHub's ``::level file=<path>,...::`` format uses ``::`` as a delimiter.
    If a path contains ``::`` (e.g. a Debtector qualified_name), the annotation
    would be malformed.  Replace any occurrence with ``/`` to keep it readable.

    Args:
        path: Raw file path or qualified_name string.

    Returns:
        Path safe to embed inside a GitHub annotation parameter value.
    """
    return path.replace("::", "/")


def _emit_github_annotations(
    new_cycles: list,
    new_gods: list,
    regressions: list,
    sev,
    new_sdp: list | None = None,
) -> None:
    """Print GitHub Actions workflow commands for each regression.

    Format: ``::level file=<path>,line=1::<message>``

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
        new_sdp: List of new SDP violation dicts (see :func:`_sdp_dict`).
    """
    if _warns(new_cycles, sev.cycles):
        level = _annotation_level(sev.cycles)
        for cycle in new_cycles:
            safe_path = _safe_annotation_path(cycle[0])
            msg = f"Import cycle: {' → '.join(cycle)}"
            print(f"::{level} file={safe_path},line=1::{msg}")

    if _warns(new_gods, sev.god_modules):
        level = _annotation_level(sev.god_modules)
        for path_str in new_gods:
            safe_path = _safe_annotation_path(path_str)
            print(
                f"::{level} file={safe_path},line=1::"
                "God module: Ca exceeds the configured percentile"
            )

    if _warns(regressions, sev.instability):
        level = _annotation_level(sev.instability)
        for r in regressions:
            safe_path = _safe_annotation_path(r["file_path"])
            msg = f"Instability: {r['before']:.3f} → {r['after']:.3f}"
            print(f"::{level} file={safe_path},line=1::{msg}")

    new_sdp = new_sdp or []
    if _warns(new_sdp, sev.instability):
        level = _annotation_level(sev.instability)
        for v in new_sdp:
            safe_path = _safe_annotation_path(v["source"])
            print(f"::{level} file={safe_path},line=1::SDP violation: {_sdp_text(v)}")


def _emit_gitlab_report(
    new_cycles: list,
    new_gods: list,
    regressions: list,
    sev,
    new_sdp: list | None = None,
) -> None:
    """Print a GitLab CI–friendly report for each regression.

    Uses GitLab's ``section_start``/``section_end`` markers for collapsible
    log sections when issues are found.

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
        new_sdp: List of new SDP violation dicts (see :func:`_sdp_dict`).
    """
    ts = int(time.time())

    if _warns(new_cycles, sev.cycles):
        label = "ERROR" if sev.cycles == Severity.ERROR else "WARNING"
        print(f"\x1b[0Ksection_start:{ts}:cycles\r\x1b[0K[{label}] New cycles ({len(new_cycles)})")
        for cycle in new_cycles:
            print("  " + " → ".join(cycle) + " → ...")
        print(f"\x1b[0Ksection_end:{ts}:cycles\r\x1b[0K")

    if _warns(new_gods, sev.god_modules):
        label = "ERROR" if sev.god_modules == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:god_modules\r\x1b[0K"
            f"[{label}] New god modules ({len(new_gods)})"
        )
        for path_str in new_gods:
            print(f"  {path_str}")
        print(f"\x1b[0Ksection_end:{ts}:god_modules\r\x1b[0K")

    if _warns(regressions, sev.instability):
        label = "ERROR" if sev.instability == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:instability\r\x1b[0K"
            f"[{label}] Instability regressions ({len(regressions)})"
        )
        for r in regressions:
            print(f"  {r['file_path']}  I: {r['before']:.3f} → {r['after']:.3f}")
        print(f"\x1b[0Ksection_end:{ts}:instability\r\x1b[0K")

    new_sdp = new_sdp or []
    if _warns(new_sdp, sev.instability):
        label = "ERROR" if sev.instability == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:sdp\r\x1b[0K[{label}] New SDP violations ({len(new_sdp)})"
        )
        for v in new_sdp:
            print(f"  {_sdp_text(v)}")
        print(f"\x1b[0Ksection_end:{ts}:sdp\r\x1b[0K")


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


def _print_section(title: str, sep: str = "─") -> None:
    """Print a section header for human-readable output."""
    print(f"\n{'━' * 4} {title} {'━' * 4}")


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
