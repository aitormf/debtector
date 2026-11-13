"""Helpers shared by the CLI commands (store, index root, test paths, output)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import structlog

from ..config import Severity, load_config
from ..graph_store import GraphStore
from ..indexer import Indexer
from ..metrics import god_modules, sdp_violations

log = structlog.get_logger()

# Metadata key: indexed directory, relative to the project root (portable if
# index.db is committed).
_INDEX_ROOT_KEY = "index_root"


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
    return _open_store(str(db_path), project)


def _open_store(db_path: str, project: str) -> GraphStore:
    """Open the index at *db_path* with the ``test_paths`` of *project* applied.

    Args:
        db_path: Path to the SQLite index.
        project: Project root whose ``debtector.toml`` defines ``test_paths``; the
            index's ``index_root`` is resolved against it.

    Returns:
        An open :class:`~debtector.graph_store.GraphStore` whose ``is_test_path``
        knows the configured test directories.
    """
    store = GraphStore(db_path)
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


def _blocks(issues: list, severity: Severity) -> bool:
    """Return True if *issues* are non-empty and *severity* is ERROR."""
    return bool(issues) and severity == Severity.ERROR


def _warns(issues: list, severity: Severity) -> bool:
    """Return True if *issues* are non-empty and *severity* is ERROR or WARNING."""
    return bool(issues) and severity in (Severity.ERROR, Severity.WARNING)


def _print_section(title: str, sep: str = "─") -> None:
    """Print a section header for human-readable output."""
    print(f"\n{'━' * 4} {title} {'━' * 4}")
