"""
CLI para CodeIndex.

Uso:
    python -m codeindex index ./mi-proyecto
    python -m codeindex search "UserService"
    python -m codeindex summary src/auth/service.py
    python -m codeindex impact src/auth/service.py
    python -m codeindex imports flask
    python -m codeindex status
"""

from __future__ import annotations

import argparse
import sys

from .graph_store import GraphStore
from .indexer import Indexer
from .logging import configure_logging


def _get_store(project: str) -> GraphStore:
    """Open the :class:`~codeindex.graph_store.GraphStore` for *project*.

    Args:
        project: Path to the project root directory.  The SQLite database is
            expected at ``<project>/.codeindex.db``.

    Returns:
        An open :class:`~codeindex.graph_store.GraphStore` instance.
    """
    import os

    db_path = os.path.join(project, ".codeindex.db")
    return GraphStore(db_path)


def cmd_index(args):
    """Run the indexer on a project directory and print a summary.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``path`` (str): Path to the project directory to index.
    """
    store = _get_store(args.path)
    indexer = Indexer(store)

    print(f"Indexando {args.path}...")
    stats = indexer.index(args.path)

    print(f"\n  Archivos escaneados:  {stats['scanned']}")
    print(f"  Indexados:            {stats['indexed']}")
    print(f"  Sin cambios:          {stats['skipped']}")
    print(f"  Errores:              {stats['errors']}")
    print(f"  Eliminados:           {stats['removed']}")
    store.close()


def cmd_search(args):
    """Search the index for symbols matching a query and print results.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``query`` (str): Free-text search query.
            - ``kind`` (str | None): Optional node kind filter (e.g. ``"Class"``).
    """
    store = _get_store(args.project)
    results = store.search_nodes(args.query, kind=args.kind)

    print(f"\nResultados para: '{args.query}'")
    print("─" * 60)
    for n in results:
        print(f"  {n.kind:10s} {n.qualified_name}")
        if n.signature:
            print(f"             {n.signature}")
        print()
    print(f"Total: {len(results)}")
    store.close()


def cmd_summary(args):
    """Print a structural summary (symbols and edges) for a single file.

    Exits with status 1 if the file is not found in the index.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``file`` (str): Relative path of the file to summarise.
    """
    store = _get_store(args.project)
    summary = store.get_file_summary(args.file)

    if not summary:
        print(f"Archivo no encontrado: {args.file}")
        store.close()
        sys.exit(1)

    print(f"\n📄 {summary['path']} ({summary['language']})")
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

    store.close()


def cmd_impact(args):
    """Perform an impact-radius analysis and print affected files and nodes.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``files`` (list[str]): List of changed file paths (seeds).
            - ``depth`` (int): Maximum traversal depth.
    """
    store = _get_store(args.project)
    result = store.get_impact_radius(args.files, max_depth=args.depth)

    print(f"\nAnálisis de impacto (profundidad {args.depth}):")
    print("─" * 60)

    print(f"\n  Nodos cambiados:   {len(result['changed_nodes'])}")
    print(f"  Nodos impactados:  {len(result['impacted_nodes'])}")
    print(f"  Archivos afectados: {len(result['impacted_files'])}")

    if result["impacted_files"]:
        print("\n  Archivos impactados:")
        for f in sorted(result["impacted_files"]):
            print(f"    📁 {f}")

    if result["impacted_nodes"]:
        print("\n  Nodos impactados:")
        for n in result["impacted_nodes"][:20]:
            print(f"    {n.kind:10s} {n.qualified_name}")
        if len(result["impacted_nodes"]) > 20:
            print(f"    ... y {len(result['impacted_nodes']) - 20} más")

    store.close()


def cmd_imports(args):
    """Search for files that import a given module and print results.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``module`` (str): Module name substring to search for.
    """
    store = _get_store(args.project)
    results = store.search_imports(args.module)

    print(f"\nArchivos que importan '{args.module}':")
    print("─" * 60)
    for r in results:
        print(f"  📁 {r['file_path']}  (línea {r['line']})")
    print(f"\nTotal: {len(results)}")
    store.close()


def cmd_status(args):
    """Print index statistics (file count, node/edge counts, breakdown by kind).

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
    """
    store = _get_store(args.project)
    stats = store.get_stats()

    print("\nEstado del índice:")
    print("─" * 40)
    print(f"  Archivos:    {stats.files_count}")
    print(f"  Nodos:       {stats.total_nodes}")
    print(f"  Aristas:     {stats.total_edges}")
    print(f"  Lenguajes:   {', '.join(stats.languages)}")

    if stats.nodes_by_kind:
        print("\n  Nodos por tipo:")
        for k, v in stats.nodes_by_kind.items():
            print(f"    {k:12s} {v}")

    if stats.edges_by_kind:
        print("\n  Aristas por tipo:")
        for k, v in stats.edges_by_kind.items():
            print(f"    {k:15s} {v}")

    store.close()


def cmd_callers(args):
    """Print all callers of a given symbol (by qualified name).

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``qualified_name`` (str): The qualified name of the target symbol.
    """
    store = _get_store(args.project)
    callers = store.callers_of(args.qualified_name)

    print(f"\n¿Quién llama a {args.qualified_name}?")
    print("─" * 60)
    for n in callers:
        print(f"  {n.kind:10s} {n.qualified_name}")
        print(f"             📁 {n.file_path}:{n.line_start}")
    print(f"\nTotal: {len(callers)}")
    store.close()


def main():
    """Entry point for the ``codeindex`` CLI.

    Configures structured logging, builds the argument parser, dispatches to
    the appropriate sub-command handler, and exits.  Prints help and exits
    with status 0 if no sub-command is provided.
    """
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="codeindex",
        description="CodeIndex - Grafo de código para reducir tokens de IA",
    )
    parser.add_argument("--project", "-p", default=".", help="Ruta al proyecto")

    sub = parser.add_subparsers(dest="command")

    # index
    p_idx = sub.add_parser("index", help="Indexar un proyecto")
    p_idx.add_argument("path", help="Ruta al proyecto")

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
    p_imports = sub.add_parser("imports", help="Buscar imports")
    p_imports.add_argument("module", help="Módulo a buscar")

    # status
    sub.add_parser("status", help="Estadísticas del índice")

    # callers
    p_callers = sub.add_parser("callers", help="¿Quién llama a un símbolo?")
    p_callers.add_argument("qualified_name", help="qualified_name del símbolo")

    args = parser.parse_args()
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
        "callers": cmd_callers,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
