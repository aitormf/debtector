"""
CLI para CodeIndex.

Uso:
    codeindex index ./mi-proyecto
    codeindex --json search "UserService"
    codeindex summary src/auth/service.py
    codeindex impact src/auth/service.py
    codeindex imports flask
    codeindex status
    codeindex install-skill --global
    codeindex install-hook [--add-to-stage]
    codeindex init
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

from .config import load_config
from .graph_store import GraphStore
from .indexer import Indexer
from .logging import configure_logging
from .metrics import compute_metrics, find_cycles, god_modules
from .models import node_to_dict

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _codeindex_dir(project: str) -> Path:
    """Return the ``.codeindex/`` directory for *project*, creating it if needed.

    Args:
        project: Path to the project root.

    Returns:
        A :class:`~pathlib.Path` pointing to ``{project}/.codeindex/``.
    """
    d = Path(project) / ".codeindex"
    d.mkdir(parents=True, exist_ok=True)
    gitignore = d / ".gitignore"
    gitignore.write_text(
        "# Managed by codeindex — do not edit manually\n*\n!.gitignore\n!baseline.json\n",
        encoding="utf-8",
    )
    return d


def _get_store(project: str) -> GraphStore:
    """Open the :class:`~codeindex.graph_store.GraphStore` for *project*.

    The SQLite database lives at ``{project}/.codeindex/index.db``.

    Args:
        project: Path to the project root directory.

    Returns:
        An open :class:`~codeindex.graph_store.GraphStore` instance.
    """
    db_path = _codeindex_dir(project) / "index.db"
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

            - ``project`` (str): Root directory where ``.codeindex/`` is stored.
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
    no forma parte del objetivo actual de codeIndex (análisis de acoplamiento para CI/PR).
    El código se conserva pero no se desarrollará más.

    Instala ``codeindex[semantic]`` si necesitas usar esta funcionalidad.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root.
            - ``query`` (str): Natural-language search string.
            - ``limit`` (int): Maximum number of results.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    msg = (
        "El comando 'semantic' está deprecado y congelado.\n"
        "La búsqueda semántica no forma parte del objetivo actual de codeIndex.\n"
        "Si aún necesitas esta funcionalidad: uv add 'codeindex[semantic]'"
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


def cmd_install_skill(args) -> None:
    """Copy CodeIndex skill files to the Claude Code skills directory.

    Installs ``codeindex.md`` and ``codeindex-bootstrap.md`` to either the
    global (``~/.claude/skills/``) or project-level (``.claude/skills/``)
    skills directory.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Path to the project root (used for project-level install).
            - ``global_install`` (bool): Install to ``~/.claude/skills/`` when ``True``.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    skills_src = Path(__file__).parent / "skills"
    if not skills_src.exists():
        msg = "skills directory not found in package"
        if args.json:
            _json_out({"error": msg})
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    if args.global_install:
        dest = Path.home() / ".claude" / "skills"
    else:
        dest = Path(args.project) / ".claude" / "skills"

    dest.mkdir(parents=True, exist_ok=True)

    installed = []
    for skill_file in sorted(skills_src.glob("*.md")):
        target = dest / skill_file.name
        shutil.copy2(skill_file, target)
        installed.append(str(target))

    if args.json:
        _json_out({"installed": installed, "dest": str(dest)})
    else:
        for path in installed:
            print(f"  Instalado: {path}")
        print(f"\nSkills instalados en: {dest}")


# ──────────────────────────────────────────────
# Git hook
# ──────────────────────────────────────────────

# Marker used to detect whether the hook is already installed
_HOOK_MARKER = "# codeindex-hook"

# Shell snippet appended to (or used as) the pre-commit hook
_HOOK_SNIPPET_BASE = """\
{marker}
# Re-index changed files before every commit (incremental, fast).
# Logs go to .codeindex/codeindex.log — never blocks the commit.
codeindex index . >/dev/null 2>&1 || true
"""

_HOOK_SNIPPET_STAGE = """\
{marker}
# Re-index changed files and stage the updated index before every commit.
codeindex index . >/dev/null 2>&1 || true
git add .codeindex/index.db 2>/dev/null || true
"""

_HOOK_SHEBANG = "#!/bin/sh\n"


def _find_git_hooks(start: str) -> Path | None:
    """Walk up from *start* to find the ``.git/hooks/`` directory.

    Args:
        start: Starting directory path (typically the project root).

    Returns:
        The :class:`~pathlib.Path` to the ``.git/hooks/`` directory, or
        ``None`` if no ``.git/`` directory is found in any ancestor.
    """
    current = Path(start).resolve()
    while True:
        hooks = current / ".git" / "hooks"
        if hooks.is_dir():
            return hooks
        parent = current.parent
        if parent == current:
            return None
        current = parent


def cmd_install_hook(args) -> None:
    """Install a git pre-commit hook that re-indexes files before every commit.

    If a pre-commit hook already exists and does not contain the codeindex
    marker, the snippet is appended rather than overwriting.  Calling this
    command twice is idempotent.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Project root used to locate ``.git/``.
            - ``add_to_stage`` (bool): When ``True``, the hook also runs
              ``git add .codeindex/index.db`` so the updated index is included
              in the commit.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    hooks_dir = _find_git_hooks(args.project)
    if hooks_dir is None:
        msg = f"no .git/ directory found from '{args.project}'"
        if args.json:
            _json_out({"error": msg})
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    hook_path = hooks_dir / "pre-commit"
    template = _HOOK_SNIPPET_STAGE if args.add_to_stage else _HOOK_SNIPPET_BASE
    snippet = template.format(marker=_HOOK_MARKER)

    # Idempotency: skip if already installed
    if hook_path.exists() and _HOOK_MARKER in hook_path.read_text(encoding="utf-8"):
        msg = f"hook already installed at {hook_path}"
        if args.json:
            _json_out({"status": "already_installed", "path": str(hook_path)})
        else:
            print(f"  Ya instalado: {hook_path}")
        return

    if hook_path.exists():
        # Append to existing hook
        existing = hook_path.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        hook_path.write_text(existing + "\n" + snippet, encoding="utf-8")
        action = "appended"
    else:
        # Create new hook with shebang
        hook_path.write_text(_HOOK_SHEBANG + "\n" + snippet, encoding="utf-8")
        action = "created"

    # Make executable
    hook_path.chmod(hook_path.stat().st_mode | 0o111)

    if args.json:
        _json_out({"status": action, "path": str(hook_path)})
    else:
        print(f"  Hook {action}: {hook_path}")
        print("\nEl índice se actualizará automáticamente antes de cada commit.")
        if args.add_to_stage:
            print("El fichero .codeindex/index.db se añadirá al stage automáticamente.")


# ──────────────────────────────────────────────
# codeindex init — git filter + hook setup
# ──────────────────────────────────────────────

# Marker and hook snippet for post-checkout / post-merge / post-rewrite
_INIT_MARKER = "# codeindex-init-hook"

_INIT_HOOK_SNIPPET = """\
{marker}
# Re-index the project after checkout/merge/rebase to keep the index current.
# Logs go to .codeindex/codeindex.log — never blocks git.
codeindex index . >/dev/null 2>&1 || true
"""

# .gitattributes line that activates the codeindex filter/diff drivers
_GITATTRIBUTES_MARKER = "filter=codeindex"
_GITATTRIBUTES_LINE = ".codeindex/index.db filter=codeindex diff=codeindex merge=ours\n"

# Git config keys/values for filter and diff drivers
_GIT_CONFIG = [
    ("filter.codeindex.clean", "codeindex-clean"),
    ("filter.codeindex.smudge", "codeindex-smudge"),
    ("filter.codeindex.required", "false"),
    ("diff.codeindex.textconv", "codeindex-clean"),
]


def _find_git_root(start: str) -> Path | None:
    """Walk up from *start* to find the git repository root.

    Args:
        start: Starting directory path (typically the project root).

    Returns:
        The :class:`~pathlib.Path` of the directory containing ``.git/``, or
        ``None`` if no git repository is found in any ancestor.
    """
    current = Path(start).resolve()
    while True:
        if (current / ".git").is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _patch_gitattributes(path: Path) -> bool:
    """Add the codeindex filter line to *path* if not already present.

    Args:
        path: Path to the ``.gitattributes`` file (may not exist yet).

    Returns:
        ``True`` if the file was modified, ``False`` if it was already
        configured.
    """
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if _GITATTRIBUTES_MARKER in content:
            return False
        if not content.endswith("\n"):
            content += "\n"
        path.write_text(content + _GITATTRIBUTES_LINE, encoding="utf-8")
    else:
        path.write_text(_GITATTRIBUTES_LINE, encoding="utf-8")
    return True


def _install_init_hook(hooks_dir: Path, hook_name: str) -> str:
    """Install or append the codeindex re-index snippet to *hook_name*.

    Calling this function a second time is idempotent (marker check).

    Args:
        hooks_dir: Path to the ``.git/hooks/`` directory.
        hook_name: Hook filename (e.g. ``"post-checkout"``).

    Returns:
        A short action string: ``"created"``, ``"appended"``, or
        ``"already_installed"``.
    """
    hook_path = hooks_dir / hook_name
    snippet = _INIT_HOOK_SNIPPET.format(marker=_INIT_MARKER)

    if hook_path.exists() and _INIT_MARKER in hook_path.read_text(encoding="utf-8"):
        return "already_installed"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        hook_path.write_text(existing + "\n" + snippet, encoding="utf-8")
        action = "appended"
    else:
        hook_path.write_text(_HOOK_SHEBANG + "\n" + snippet, encoding="utf-8")
        action = "created"

    hook_path.chmod(hook_path.stat().st_mode | 0o111)
    return action


def cmd_init(args) -> None:
    """Configure the git repository to share the codeindex database.

    Performs three idempotent steps:

    1. Writes ``filter.codeindex`` and ``diff.codeindex`` drivers to the
       local git config (never the global one).
    2. Adds the ``.codeindex/index.db`` filter line to ``.gitattributes``.
    3. Installs ``post-checkout``, ``post-merge``, and ``post-rewrite`` hooks
       that re-index the project after any git operation that changes files.

    Once set up, the binary SQLite database is stored in git as a portable
    SQL text dump.  On checkout the dump is converted back to SQLite
    automatically.  After every merge or checkout git re-runs the indexer so
    the local index always reflects the current working tree.

    Args:
        args: Parsed argument namespace.  Expected attributes:

            - ``project`` (str): Project root used to locate ``.git/``.
            - ``json`` (bool): Emit JSON instead of human-readable text.
    """
    git_root = _find_git_root(args.project)
    if git_root is None:
        msg = f"no .git/ directory found from '{args.project}'"
        if args.json:
            _json_out({"error": msg})
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    steps: list[str] = []

    # 1. Configure git filter / diff drivers (local config only)
    # nosec B603 B607 — fixed args, no user input in the command list
    for key, value in _GIT_CONFIG:
        subprocess.run(  # nosec B603 B607
            ["git", "config", key, value],
            cwd=git_root,
            check=True,
            capture_output=True,
        )
    steps.append("Configurados filtros git (filter.codeindex, diff.codeindex)")

    # 2. Patch .gitattributes
    ga_path = git_root / ".gitattributes"
    changed = _patch_gitattributes(ga_path)
    steps.append(f"Parcheado {ga_path}" if changed else f"Ya configurado: {ga_path}")

    # 3. Install post-checkout / post-merge / post-rewrite hooks
    hooks_dir = git_root / ".git" / "hooks"
    for hook_name in ("post-checkout", "post-merge", "post-rewrite"):
        action = _install_init_hook(hooks_dir, hook_name)
        steps.append(f"Hook {hook_name}: {action}")

    if args.json:
        _json_out({"status": "ok", "steps": steps})
    else:
        for step in steps:
            print(f"  ✓ {step}")
        print("\ncodeindex init completado. El índice se compartirá automáticamente vía git.")


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# Baseline
# ──────────────────────────────────────────────

_BASELINE_FILE = ".codeindex/baseline.json"
# Tolerancia de inestabilidad: diferencia mínima para considerar una regresión.
# Un delta < 5% se trata como ruido de redondeo, no como degradación real.
_INSTABILITY_TOLERANCE = 0.05


def _baseline_path(project: str) -> Path:
    return Path(project) / _BASELINE_FILE


def cmd_baseline(args) -> None:
    """Save or compare coupling metrics against a stored baseline.

    Sub-commands:

    * ``save``   — snapshot current metrics to ``.codeindex/baseline.json``.
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
        print("Uso: codeindex baseline <save|status>", file=sys.stderr)
        sys.exit(1)


def _baseline_save(args) -> None:
    """Snapshot current metrics to ``.codeindex/baseline.json``."""
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
    severity configured in ``codeindex.toml``:

    - ``error``   — contributes to exit code 1 (blocks CI).
    - ``warning`` — printed but does not block CI (exit 0).
    - ``info``    — silent; neither printed nor blocking.
    """
    path = _baseline_path(args.project)

    if not path.exists():
        if args.json:
            _json_out({"error": "no baseline — ejecuta: codeindex baseline save"})
        else:
            print("Sin baseline. Ejecuta primero: codeindex baseline save")
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

    from .config import Severity  # noqa: PLC0415

    # Determinar si cada tipo de regresión bloquea el CI según su severidad
    def _blocks(issues: list, severity: Severity) -> bool:
        return bool(issues) and severity == Severity.ERROR

    def _warns(issues: list, severity: Severity) -> bool:
        return bool(issues) and severity in (Severity.ERROR, Severity.WARNING)

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

    if not has_any_warning:
        print("✓  Sin cambios respecto al baseline")
        if has_blocking:
            sys.exit(1)
        return

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


# ──────────────────────────────────────────────
# Métricas de acoplamiento
# ──────────────────────────────────────────────


def cmd_metrics(args) -> None:
    """Print coupling metrics (Ca, Ce, I, cycles, god modules) for every module.

    Reads ``codeindex.toml`` from the project root to apply configured
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
        print("Sin datos — ejecuta primero: codeindex index <directorio>")
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
        if m.instability >= instability_warn and (m.fan_in + m.fan_out) > 0:
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


# Entry point
# ──────────────────────────────────────────────


def main() -> None:
    """Entry point for the ``codeindex`` CLI.

    Parses arguments first, then configures structured logging so that the
    correct project path (and therefore log file location) is known.
    Dispatches to the appropriate sub-command handler and exits.
    Prints help and exits with status 0 if no sub-command is provided.
    """
    parser = argparse.ArgumentParser(
        prog="codeindex",
        description="CodeIndex - Grafo de código para reducir tokens de IA",
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
    p_baseline_sub.add_parser("status", help="Comparar métricas actuales con el baseline")

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

    # metrics
    p_metrics = sub.add_parser(
        "metrics", help="Métricas de acoplamiento (Ca, Ce, I, ciclos, god modules)"
    )
    p_metrics.add_argument(
        "--sort",
        choices=["fan_in", "fan_out", "instability"],
        default="fan_in",
        help="Columna de ordenación (default: fan_in)",
    )
    p_metrics.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Número máximo de filas a mostrar",
    )

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

    # install-skill
    p_skill = sub.add_parser("install-skill", help="Instalar skills en Claude Code")
    p_skill.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        default=False,
        help="Instalar en ~/.claude/skills/ (global) en lugar de .claude/skills/ (proyecto)",
    )

    # install-hook
    p_hook = sub.add_parser("install-hook", help="Instalar hook git pre-commit para auto-indexado")
    p_hook.add_argument(
        "--add-to-stage",
        dest="add_to_stage",
        action="store_true",
        default=False,
        help="El hook también hace 'git add .codeindex/index.db' para commitear el índice",
    )

    # init
    sub.add_parser(
        "init",
        help=(
            "Configurar el repo git para compartir el índice entre desarrolladores: "
            "instala filtros git clean/smudge y hooks post-checkout/merge/rewrite"
        ),
    )

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
        "metrics": cmd_metrics,
        "baseline": cmd_baseline,
        "callers": cmd_callers,
        "untested": cmd_untested,
        "install-skill": cmd_install_skill,
        "install-hook": cmd_install_hook,
        "init": cmd_init,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
