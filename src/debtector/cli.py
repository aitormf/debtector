"""
CLI para Debtector.

Uso:
    debtector index ./mi-proyecto
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
import sys
import time
from pathlib import Path

import structlog

from .config import Severity, load_config
from .git_history import (
    compute_bus_factor,
    compute_hotspots,
    compute_temporal_coupling,
)
from .graph_store import GraphStore
from .indexer import Indexer
from .logging import configure_logging
from .metrics import compute_metrics, find_cycles, god_modules
from .models import node_to_dict

log = structlog.get_logger()

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

    Args:
        project: Path to the project root directory.
    """
    try:
        indexer = Indexer(project)
        indexer.index(project)
    except Exception:  # noqa: BLE001
        # Never let a failed auto-index abort the analysis command that called it.
        log.warning("auto_index_failed", project=project, exc_info=True)


def _get_store(project: str) -> GraphStore:
    """Open the :class:`~debtector.graph_store.GraphStore` for *project*.

    The SQLite database lives at ``{project}/.debtector/index.db``.

    Args:
        project: Path to the project root directory.

    Returns:
        An open :class:`~debtector.graph_store.GraphStore` instance.
    """
    db_path = _debtector_dir(project) / "index.db"
    return GraphStore(str(db_path))


def _json_out(data) -> None:
    """Print *data* as compact JSON to stdout.

    Args:
        data: Any JSON-serialisable object.
    """
    print(json.dumps(data, default=str))


# ──────────────────────────────────────────────
# Subcomandos
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
        print(f"Indexando {args.path}...")

    stats = indexer.index(args.path)
    store.close()

    if args.json:
        _json_out(stats)
    else:
        print(f"\n  Archivos escaneados:  {stats['scanned']}")
        print(f"  Indexados:            {stats['indexed']}")
        print(f"  Sin cambios:          {stats['skipped']}")
        print(f"  Errores:              {stats['errors']}")
        print(f"  Eliminados:           {stats['removed']}")


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
        print(f"\nResultados para: '{args.query}'")
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
            print(f"Archivo no encontrado: {args.file}")
        sys.exit(1)

    if args.json:
        _json_out(summary)
    else:
        print(f"\n{summary['path']} ({summary['language']})")
        print("─" * 60)
        if summary["nodes"]:
            print("\n  Símbolos:")
            for s in summary["nodes"]:
                parent = "  └─ " if s["parent"] else "  "
                print(f"    {parent}{s['kind']:10s} {s.get('signature') or s['name']}")
        if summary["edges"]:
            print("\n  Relaciones:")
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
        print(f"\nAnálisis de impacto (profundidad {args.depth}):")
        print("─" * 60)
        print(f"\n  Nodos cambiados:    {len(result['changed_nodes'])}")
        print(f"  Nodos impactados:   {len(result['impacted_nodes'])}")
        print(f"  Archivos afectados: {len(result['impacted_files'])}")
        if result["impacted_files"]:
            print("\n  Archivos impactados:")
            for f in sorted(result["impacted_files"]):
                print(f"    {f}")
        if result["impacted_nodes"]:
            print("\n  Nodos impactados:")
            for n in result["impacted_nodes"][:20]:
                print(f"    {n.kind:10s} {n.qualified_name}")
            if len(result["impacted_nodes"]) > 20:
                print(f"    ... y {len(result['impacted_nodes']) - 20} más")


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
        print(f"\nArchivos que importan '{args.module}':")
        print("─" * 60)
        for r in results:
            print(f"  {r['file_path']}  (línea {r['line']})")
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
                "embeddings_count": stats.embeddings_count,
            }
        )
    else:
        print("\nEstado del índice:")
        print("─" * 40)
        print(f"  Archivos:    {stats.files_count}")
        print(f"  Nodos:       {stats.total_nodes}")
        print(f"  Aristas:     {stats.total_edges}")
        print(f"  Embeddings:  {stats.embeddings_count}")
        print(f"  Lenguajes:   {', '.join(stats.languages)}")
        if stats.nodes_by_kind:
            print("\n  Nodos por tipo:")
            for k, v in stats.nodes_by_kind.items():
                print(f"    {k:12s} {v}")
        if stats.edges_by_kind:
            print("\n  Aristas por tipo:")
            for k, v in stats.edges_by_kind.items():
                print(f"    {k:15s} {v}")


def cmd_semantic(args) -> None:
    """[DEPRECADO] Búsqueda semántica por concepto.

    Este comando está congelado. La búsqueda semántica (embeddings + sqlite-vec)
    no forma parte del objetivo actual de debtector (análisis de acoplamiento para CI/PR).
    El código se conserva pero no se desarrollará más.

    Instala ``debtector[semantic]`` si necesitas usar esta funcionalidad.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``query`` (str): Natural-language search string.
            - ``limit`` (int): Maximum number of results.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    msg = (
        "El comando 'semantic' está deprecado y congelado.\n"
        "La búsqueda semántica no forma parte del objetivo actual de debtector.\n"
        "Si aún necesitas esta funcionalidad: uv add 'debtector[semantic]'"
    )
    if args.json:
        _json_out({"error": msg})
    else:
        print(f"DEPRECADO: {msg}", file=sys.stderr)
    sys.exit(1)


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
        print(f"\n¿Quién llama a {args.qualified_name}?")
        print("─" * 60)
        for n in callers:
            print(f"  {n.kind:10s} {n.qualified_name}")
            print(f"             {n.file_path}:{n.line_start}")
        print(f"\nTotal: {len(callers)}")


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
        print(f"\nSímbolos sin test ({len(symbols)}):")
        print("─" * 60)
        for n in symbols:
            print(f"  {n.kind:10s} {n.name}")
            print(f"             {n.file_path}:{n.line_start}")


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# Baseline
# ──────────────────────────────────────────────

_BASELINE_FILE = ".debtector/baseline.json"
# Tolerancia de inestabilidad: diferencia mínima para considerar una regresión.
# Un delta < 5% se trata como ruido de redondeo, no como degradación real.
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
        print("Uso: debtector baseline <save|status>", file=sys.stderr)
        sys.exit(1)


def _baseline_save(args) -> None:
    """Snapshot current metrics to ``.debtector/baseline.json``."""
    cfg = load_config(args.project)
    store = _get_store(args.project)
    modules = compute_metrics(store)
    cycles = find_cycles(store)
    gods = god_modules(store, percentile=cfg.metrics.thresholds.god_module_percentile)
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
    }

    path = _baseline_path(args.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if args.json:
        _json_out({"status": "saved", "path": str(path), "modules": len(modules)})
    else:
        print(f"Baseline guardado: {path}  ({len(modules)} módulos)")


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
            _json_out({"error": "no baseline — ejecuta: debtector baseline save"})
        else:
            print("Sin baseline. Ejecuta primero: debtector baseline save")
        return

    baseline = json.loads(path.read_text(encoding="utf-8"))
    baseline_cycles = [frozenset(c) for c in baseline.get("cycles", [])]
    baseline_gods = set(baseline.get("god_modules", []))

    cfg = load_config(args.project)
    sev = cfg.metrics.severity
    store = _get_store(args.project)
    current_modules = compute_metrics(store)
    current_cycles = find_cycles(store)
    current_gods = god_modules(store, percentile=cfg.metrics.thresholds.god_module_percentile)
    store.close()

    # Detectar regresiones por tipo
    new_cycles = [c for c in current_cycles if frozenset(c) not in baseline_cycles]
    new_gods = [m.file_path for m in current_gods if m.file_path not in baseline_gods]

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

    # Determinar si cada tipo de regresión bloquea el CI según su severidad
    has_blocking = (
        _blocks(new_cycles, sev.cycles)
        or _blocks(new_gods, sev.god_modules)
        or _blocks(regressions, sev.instability)
    )

    if args.json:
        _json_out(
            {
                "regressions": regressions,
                "new_cycles": new_cycles,
                "new_god_modules": new_gods,
            }
        )
        if has_blocking:
            sys.exit(1)
        return

    has_any_warning = (
        _warns(new_cycles, sev.cycles)
        or _warns(new_gods, sev.god_modules)
        or _warns(regressions, sev.instability)
    )

    reporter = getattr(args, "reporter", None)

    if not has_any_warning:
        print("✓  Sin cambios respecto al baseline")
        return

    if reporter == "github":
        _emit_github_annotations(new_cycles, new_gods, regressions, sev)
    elif reporter == "gitlab":
        _emit_gitlab_report(new_cycles, new_gods, regressions, sev)
    else:
        if _warns(new_cycles, sev.cycles):
            label = "⛔" if sev.cycles == Severity.ERROR else "⚠"
            print(f"\n{label}  Nuevos ciclos ({len(new_cycles)}):")
            for cycle in new_cycles:
                print("   " + " → ".join(cycle) + " → ...")

        if _warns(new_gods, sev.god_modules):
            label = "⛔" if sev.god_modules == Severity.ERROR else "⚠"
            print(f"\n{label}  Nuevos god modules ({len(new_gods)}):")
            for path_str in new_gods:
                print(f"   {path_str}")

        if _warns(regressions, sev.instability):
            label = "⛔" if sev.instability == Severity.ERROR else "⚠"
            print(f"\n{label}  Regresiones de inestabilidad ({len(regressions)}):")
            for r in regressions:
                print(f"   {r['file_path']}  I: {r['before']:.3f} → {r['after']:.3f}")

    if has_blocking:
        sys.exit(1)


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
) -> None:
    """Print GitHub Actions workflow commands for each regression.

    Format: ``::level file=<path>,line=1::<message>``

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
    """
    if _warns(new_cycles, sev.cycles):
        level = _annotation_level(sev.cycles)
        for cycle in new_cycles:
            safe_path = _safe_annotation_path(cycle[0])
            msg = f"Ciclo de importación: {' → '.join(cycle)}"
            print(f"::{level} file={safe_path},line=1::{msg}")

    if _warns(new_gods, sev.god_modules):
        level = _annotation_level(sev.god_modules)
        for path_str in new_gods:
            safe_path = _safe_annotation_path(path_str)
            print(
                f"::{level} file={safe_path},line=1::God module: Ca excede el percentil configurado"
            )

    if _warns(regressions, sev.instability):
        level = _annotation_level(sev.instability)
        for r in regressions:
            safe_path = _safe_annotation_path(r["file_path"])
            msg = f"Inestabilidad: {r['before']:.3f} → {r['after']:.3f}"
            print(f"::{level} file={safe_path},line=1::{msg}")


def _emit_gitlab_report(
    new_cycles: list,
    new_gods: list,
    regressions: list,
    sev,
) -> None:
    """Print a GitLab CI–friendly report for each regression.

    Uses GitLab's ``section_start``/``section_end`` markers for collapsible
    log sections when issues are found.

    Args:
        new_cycles: List of cycle node lists.
        new_gods: List of god module file paths.
        regressions: List of instability regression dicts.
        sev: :class:`~debtector.config.MetricsSeverity` instance.
    """
    ts = int(time.time())

    if _warns(new_cycles, sev.cycles):
        label = "ERROR" if sev.cycles == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:cycles\r\x1b[0K[{label}] Nuevos ciclos ({len(new_cycles)})"
        )
        for cycle in new_cycles:
            print("  " + " → ".join(cycle) + " → ...")
        print(f"\x1b[0Ksection_end:{ts}:cycles\r\x1b[0K")

    if _warns(new_gods, sev.god_modules):
        label = "ERROR" if sev.god_modules == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:god_modules\r\x1b[0K"
            f"[{label}] Nuevos god modules ({len(new_gods)})"
        )
        for path_str in new_gods:
            print(f"  {path_str}")
        print(f"\x1b[0Ksection_end:{ts}:god_modules\r\x1b[0K")

    if _warns(regressions, sev.instability):
        label = "ERROR" if sev.instability == Severity.ERROR else "WARNING"
        print(
            f"\x1b[0Ksection_start:{ts}:instability\r\x1b[0K"
            f"[{label}] Regresiones de inestabilidad ({len(regressions)})"
        )
        for r in regressions:
            print(f"  {r['file_path']}  I: {r['before']:.3f} → {r['after']:.3f}")
        print(f"\x1b[0Ksection_end:{ts}:instability\r\x1b[0K")


# ──────────────────────────────────────────────
# Acoplamiento estructural (ex-metrics)
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
    gods = god_modules(store, percentile=cfg.metrics.thresholds.god_module_percentile)
    store.close()

    god_paths = {m.file_path for m in gods}

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
                    }
                    for m in modules
                ],
                "cycles": cycles,
                "god_modules": [m.file_path for m in gods],
            }
        )
        return

    if not modules:
        print("Sin datos — ejecuta primero: debtector index <directorio>")
        return

    # Ordenar
    sort_key = getattr(args, "sort", "fan_in")
    modules_sorted = sorted(modules, key=lambda m: getattr(m, sort_key, 0), reverse=True)
    if args.limit:
        modules_sorted = modules_sorted[: args.limit]

    # Cabecera
    col_w = max((len(m.file_path) for m in modules_sorted), default=30)
    col_w = max(col_w, 30)
    header = f"{'Módulo':<{col_w}}  {'Ca':>6}  {'Ce':>6}  {'I':>6}  {'Flags'}"
    print()
    print(header)
    print("─" * len(header))

    instability_warn = cfg.metrics.thresholds.instability_threshold
    for m in modules_sorted:
        flags = ""
        if m.file_path in god_paths:
            flags += " ● god"
        if m.fan_in > 0 and m.instability >= instability_warn:
            flags += " ⚠ inestable"
        print(
            f"{m.file_path:<{col_w}}  {m.fan_in:>6.1f}  {m.fan_out:>6.1f}"
            f"  {m.instability:>6.3f}  {flags}"
        )

    print("─" * len(header))
    print(f"Total: {len(modules)} módulos")

    # Ciclos
    if cycles:
        print(f"\n⚠  Ciclos detectados ({len(cycles)}):")
        for cycle in cycles:
            print("   " + " → ".join(cycle) + " → ...")
    else:
        print("\n✓  Sin ciclos")

    # God modules
    if gods:
        print(f"\n● God modules (Ca > p{int(cfg.metrics.thresholds.god_module_percentile)}):")
        for m in gods:
            print(f"   {m.file_path}  Ca={m.fan_in:.1f}")


# Backward-compat alias — keeps existing imports and tests working
cmd_metrics = cmd_coupling


# ──────────────────────────────────────────────
# Git-coupling: behavioral analysis
# ──────────────────────────────────────────────


def cmd_hotspots(args) -> None:
    """Print hotspot ranking: files with high churn × structural coupling.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``json`` (bool): Emit JSON.
            - ``limit`` (int | None): Max results.
            - ``since`` (str | None): Date filter (e.g. ``"6 months ago"``).
            - ``min_coupling`` (float): Minimum coupling to include. Default 0.
    """
    _auto_index(args.project)
    store = _get_store(args.project)
    hotspots = compute_hotspots(
        store,
        args.project,
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
                        "coupling": round(h.coupling, 2),
                        "hotspot_score": round(h.hotspot_score, 2),
                    }
                    for h in hotspots
                ]
            }
        )
        return

    if not hotspots:
        print("Sin hotspots — ejecuta primero: debtector index <directorio>")
        return

    col_w = max((len(h.file_path) for h in hotspots), default=30)
    col_w = max(col_w, 30)
    header = f"{'Módulo':<{col_w}}  {'Churn':>7}  {'Coupling':>9}  {'Score':>8}"
    print()
    print(header)
    print("─" * len(header))
    for h in hotspots:
        print(f"{h.file_path:<{col_w}}  {h.churn:>7}  {h.coupling:>9.2f}  {h.hotspot_score:>8.2f}")
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
    pairs = compute_temporal_coupling(
        args.project,
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
        print("Sin acoplamiento temporal detectado")
        return

    col_w = max(
        (max(len(t.file_a), len(t.file_b)) for t in pairs),
        default=30,
    )
    col_w = max(col_w, 25)
    header = f"{'Archivo A':<{col_w}}  {'Archivo B':<{col_w}}  {'Commits':>7}  {'Ratio':>6}"
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
    store = _get_store(args.project)
    results = compute_bus_factor(store, args.project)
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
        print("Sin datos — ejecuta primero: debtector index <directorio>")
        return

    col_w = max((len(b.file_path) for b in results), default=30)
    col_w = max(col_w, 30)
    aut_w = max((len(b.top_author) for b in results), default=15)
    aut_w = max(aut_w, 15)
    header = f"{'Módulo':<{col_w}}  {'Top autor':<{aut_w}}  {'% líneas':>9}  {'Bus factor':>10}"
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
    print(f"Total: {len(results)} archivos analizados")


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
    store = _get_store(args.project)
    hotspots = compute_hotspots(
        store,
        args.project,
        since=getattr(args, "since", None),
        limit=getattr(args, "limit", None),
    )
    temporal = compute_temporal_coupling(
        args.project,
        min_shared=getattr(args, "min_shared", 5),
        min_ratio=getattr(args, "min_ratio", 0.3),
        since=getattr(args, "since", None),
    )
    bus = compute_bus_factor(store, args.project)
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
                f"  {h.file_path:<{col_w}}  churn={h.churn}  coupling={h.coupling:.2f}"
                f"  score={h.hotspot_score:.2f}"
            )
    else:
        print("  (sin datos)")

    _print_section("Acoplamiento temporal", "─")
    if temporal:
        for t in temporal:
            print(
                f"  {t.file_a}  ↔  {t.file_b}"
                f"  ({t.shared_commits} commits, ratio={t.coupling_ratio:.3f})"
            )
    else:
        print("  (sin datos)")

    _print_section("Bus factor", "─")
    if bus:
        for b in bus:
            risk = " ⚠" if b.bus_factor == 1 else ""
            print(
                f"  {b.file_path}  {b.top_author}"
                f" ({b.top_author_pct:.1f}%)  bf={b.bus_factor}{risk}"
            )
    else:
        print("  (sin datos)")


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

    # ── Structural coupling ──
    cfg = load_config(args.project)
    store = _get_store(args.project)
    modules = compute_metrics(store)
    cycles = find_cycles(store)
    gods = god_modules(store, percentile=cfg.metrics.thresholds.god_module_percentile)
    god_paths = {m.file_path for m in gods}

    # ── Behavioral coupling ──
    hotspots = compute_hotspots(
        store,
        args.project,
        since=getattr(args, "since", None),
        limit=getattr(args, "limit", None),
    )
    temporal = compute_temporal_coupling(
        args.project,
        min_shared=getattr(args, "min_shared", 5),
        min_ratio=getattr(args, "min_ratio", 0.3),
        since=getattr(args, "since", None),
    )
    bus = compute_bus_factor(store, args.project)
    store.close()

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
                    }
                    for m in modules
                ],
                "cycles": cycles,
                "god_modules": [m.file_path for m in gods],
                "hotspots": [
                    {
                        "file_path": h.file_path,
                        "churn": h.churn,
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

    # Human output
    _print_section("Acoplamiento estructural")
    if modules:
        sort_key = getattr(args, "sort", "fan_in")
        mods_sorted = sorted(modules, key=lambda m: getattr(m, sort_key, 0), reverse=True)
        col_w = max((len(m.file_path) for m in mods_sorted), default=30)
        col_w = max(col_w, 30)
        print(f"  {'Módulo':<{col_w}}  {'Ca':>6}  {'Ce':>6}  {'I':>6}")
        for m in mods_sorted:
            flags = " ● god" if m.file_path in god_paths else ""
            print(
                f"  {m.file_path:<{col_w}}  {m.fan_in:>6.1f}"
                f"  {m.fan_out:>6.1f}  {m.instability:>6.3f}{flags}"
            )
    else:
        print("  (sin datos)")

    _print_section("Git-coupling")
    # Delegate to git-coupling human output via shared logic
    if hotspots:
        print("  Hotspots:")
        for h in hotspots[:5]:
            print(f"    {h.file_path}  score={h.hotspot_score:.2f}")
    if temporal:
        print("  Acoplamiento temporal:")
        for t in temporal[:5]:
            print(f"    {t.file_a}  ↔  {t.file_b}  ({t.shared_commits} commits)")
    if bus:
        print("  Bus factor:")
        for b in bus[:5]:
            risk = " ⚠" if b.bus_factor == 1 else ""
            print(f"    {b.file_path}  bf={b.bus_factor}{risk}")
    if not hotspots and not temporal and not bus:
        print("  (sin datos de git)")


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
        description="Debtector - Guardarraíl de acoplamiento para CI/PR",
    )
    parser.add_argument("--project", "-p", default=".", help="Ruta al proyecto")
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emitir JSON compacto en stdout (para consumo por IA)",
    )

    sub = parser.add_subparsers(dest="command")

    # index
    p_idx = sub.add_parser("index", help="Indexar un proyecto")
    p_idx.add_argument("path", help="Ruta al directorio a indexar")

    # search
    p_search = sub.add_parser("search", help="Buscar símbolos")
    p_search.add_argument("query", help="Texto a buscar")
    p_search.add_argument("--kind", "-k", help="Filtrar: Class, Function, Method")

    # summary
    p_sum = sub.add_parser("summary", help="Resumen de un archivo")
    p_sum.add_argument("file", help="Ruta relativa del archivo")

    # impact
    p_imp = sub.add_parser("impact", help="Análisis de impacto")
    p_imp.add_argument("files", nargs="+", help="Archivos modificados")
    p_imp.add_argument("--depth", "-d", type=int, default=2, help="Profundidad máxima")

    # imports
    p_imports = sub.add_parser("imports", help="Buscar imports de un módulo")
    p_imports.add_argument("module", help="Módulo a buscar")

    # status
    sub.add_parser("status", help="Estadísticas del índice")

    # baseline
    p_baseline = sub.add_parser("baseline", help="Gestión del baseline de métricas")
    p_baseline_sub = p_baseline.add_subparsers(dest="baseline_cmd")
    p_baseline_sub.add_parser("save", help="Guardar snapshot de métricas como baseline")
    p_status = p_baseline_sub.add_parser(
        "status", help="Comparar métricas actuales con el baseline"
    )
    p_status.add_argument(
        "--reporter",
        choices=["github", "gitlab"],
        default=None,
        help="Formato CI: github (Annotations) o gitlab (section markers)",
    )
    # semantic (congelado — no forma parte del objetivo CI/PR)
    p_sem = sub.add_parser(
        "semantic",
        help="[DEPRECADO] Búsqueda semántica por concepto. Congelado; no se desarrollará más.",
    )
    p_sem.add_argument("query", help="Query en lenguaje natural")
    p_sem.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Número máximo de resultados (default: 10)",
    )

    # coupling (ex-metrics)
    p_coupling = sub.add_parser(
        "coupling", help="Acoplamiento estructural (Ca, Ce, I, ciclos, god modules)"
    )
    p_coupling.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
        help="Columna de ordenación (default: fan_in)",
    )
    p_coupling.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Número máximo de filas a mostrar",
    )

    # metrics — deprecated alias for coupling
    p_metrics_alias = sub.add_parser(
        "metrics",
        help="[DEPRECADO] Usa 'coupling'. Métricas de acoplamiento estructural.",
    )
    p_metrics_alias.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
    )
    p_metrics_alias.add_argument("--limit", "-l", type=int, default=None)

    # callers
    p_callers = sub.add_parser("callers", help="¿Quién llama a un símbolo?")
    p_callers.add_argument("qualified_name", help="qualified_name del símbolo")

    # untested
    p_untested = sub.add_parser("untested", help="Símbolos sin tests (sin arista COVERS)")
    p_untested.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Ruta o prefijo de directorio para filtrar (opcional)",
    )

    # hotspots
    p_hotspots = sub.add_parser("hotspots", help="Hotspots: churn × acoplamiento estructural")
    p_hotspots.add_argument("--limit", "-l", type=int, default=None)
    p_hotspots.add_argument("--since", default=None, help="Filtro de fecha (e.g. '6 months ago')")
    p_hotspots.add_argument("--min-coupling", type=float, default=0.0, dest="min_coupling")

    # temporal-coupling
    p_tc = sub.add_parser("temporal-coupling", help="Archivos que co-cambian frecuentemente")
    p_tc.add_argument("--limit", "-l", type=int, default=None)
    p_tc.add_argument("--since", default=None)
    p_tc.add_argument("--min-shared", type=int, default=5, dest="min_shared")
    p_tc.add_argument("--min-ratio", type=float, default=0.3, dest="min_ratio")

    # bus-factor
    p_bus = sub.add_parser("bus-factor", help="Riesgo de autor único por archivo")
    p_bus.add_argument("--limit", "-l", type=int, default=None)

    # git-coupling
    p_git = sub.add_parser(
        "git-coupling", help="Análisis behavioral completo: hotspots + temporal + bus factor"
    )
    p_git.add_argument("--limit", "-l", type=int, default=None)
    p_git.add_argument("--since", default=None)
    p_git.add_argument("--min-shared", type=int, default=5, dest="min_shared")
    p_git.add_argument("--min-ratio", type=float, default=0.3, dest="min_ratio")

    # report
    p_report = sub.add_parser(
        "report", help="Informe completo: acoplamiento estructural + behavioral"
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
        "semantic": cmd_semantic,
        "summary": cmd_summary,
        "impact": cmd_impact,
        "imports": cmd_imports,
        "status": cmd_status,
        "coupling": cmd_coupling,
        "metrics": cmd_coupling,  # deprecated alias
        "baseline": cmd_baseline,
        "callers": cmd_callers,
        "untested": cmd_untested,
        "hotspots": cmd_hotspots,
        "temporal-coupling": cmd_temporal_coupling,
        "bus-factor": cmd_bus_factor,
        "git-coupling": cmd_git_coupling,
        "report": cmd_report,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
