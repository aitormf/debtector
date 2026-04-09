"""
Indexador principal: conecta parsers con el GraphStore.

Recorre el proyecto, detecta archivos nuevos/modificados, los parsea
con Tree-sitter y almacena los nodos y aristas en el GraphStore.
"""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import structlog

from .graph_store import GraphStore
from .models import NodeKind
from .parser import ParserRegistry
from .parser.base import LanguageParser

log = structlog.get_logger()

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".next",
    ".nuxt",
    "dist",
    "build",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".env",
    ".idea",
    ".vscode",
    "coverage",
    ".eggs",
}

DEFAULT_IGNORE_FILES = {".DS_Store", "Thumbs.db"}

CODEINDEXIGNORE = ".codeindexignore"


class IgnoreRules:
    """Parses and applies patterns from a ``.codeindexignore`` file.

    Supports:
    - Exact filename patterns (``secret.py``)
    - Glob wildcards (``*.generated.py``, ``src/*/generated.py``)
    - Directory patterns with or without trailing slash (``vendor/``, ``vendor``)
    - Comment lines starting with ``#`` and blank lines are ignored
    """

    def __init__(self, patterns: list[str]) -> None:
        """Initialize with an explicit list of patterns.

        Args:
            patterns: List of gitignore-style patterns.
        """
        self._patterns: list[str] = patterns

    @classmethod
    def from_file(cls, project_path: Path) -> IgnoreRules:
        """Load patterns from ``<project_path>/.codeindexignore``.

        If the file does not exist, an instance with no patterns is returned.

        Args:
            project_path: Root directory that may contain ``.codeindexignore``.

        Returns:
            Populated :class:`IgnoreRules` instance.
        """
        ignore_file = project_path / CODEINDEXIGNORE
        if not ignore_file.exists():
            return cls([])
        patterns: list[str] = []
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return cls(patterns)

    def is_ignored(self, rel_path: str) -> bool:
        """Return ``True`` if *rel_path* matches any stored pattern.

        *rel_path* must be a POSIX-style path relative to the project root
        (e.g. ``src/auth/service.py``).

        Matching rules:
        - A pattern ending in ``/`` (or a bare name with no ``/``) is treated
          as a directory pattern: it matches any path whose directory components
          include a segment matching the pattern.
        - Otherwise the pattern is matched against the full relative path and
          also against the file's basename using :func:`fnmatch`.

        Args:
            rel_path: Relative path to test (forward slashes).

        Returns:
            ``True`` if the path should be ignored.
        """
        if not self._patterns:
            return False

        # Normalise to forward slashes for consistent matching
        rel_path = rel_path.replace(os.sep, "/")
        p = PurePosixPath(rel_path)
        parts = p.parts  # e.g. ('src', 'auth', 'service.py')
        name = p.name  # e.g. 'service.py'

        for pattern in self._patterns:
            is_dir_pattern = pattern.endswith("/") or "/" not in pattern and "." not in pattern
            clean = pattern.rstrip("/")

            if is_dir_pattern and "/" not in clean:
                # Bare directory name: match against every directory component
                for part in parts[:-1]:
                    if fnmatch(part, clean):
                        return True
            elif is_dir_pattern:
                # Path-like directory pattern (e.g. "src/generated/")
                # Check whether any prefix of the path matches the pattern
                for i in range(1, len(parts)):
                    prefix = "/".join(parts[:i])
                    if fnmatch(prefix, clean):
                        return True
            else:
                # File pattern: match full path or just the filename
                if fnmatch(rel_path, pattern) or fnmatch(name, pattern):
                    return True

        return False


class Indexer:
    """
    Orquestador de indexación.

    Uso:
        store = GraphStore(".codeindex.db")
        indexer = Indexer(store)
        stats = indexer.index("./mi-proyecto")
    """

    def __init__(
        self,
        store: GraphStore,
        ignore_dirs: set[str] | None = None,
        ignore_files: set[str] | None = None,
    ):
        """Initialize the Indexer.

        Args:
            store: :class:`~codeindex.graph_store.GraphStore` instance where
                parsed data will be written.
            ignore_dirs: Set of directory names to skip during traversal.
                Defaults to :data:`DEFAULT_IGNORE_DIRS`.
            ignore_files: Set of exact file names to skip.
                Defaults to :data:`DEFAULT_IGNORE_FILES`.
        """
        self.store = store
        self.registry = ParserRegistry()
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.ignore_files = ignore_files or DEFAULT_IGNORE_FILES

    def index(self, project_path: str) -> dict:
        """Index a project directory with incremental change detection.

        Walks *project_path* recursively, skips ignored directories and
        unsupported file types, computes a SHA-256 hash for each file, and
        only re-parses files that have changed since the last run.  Files that
        no longer exist on disk are removed from the store.

        Args:
            project_path: Absolute or relative path to the project root.

        Returns:
            Dict with integer counters:
            ``scanned``, ``indexed``, ``skipped``, ``errors``, ``removed``.
        """
        project_path = os.path.abspath(project_path)
        stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0, "removed": 0}
        idx_log = log.bind(project=project_path)
        idx_log.info("indexing_started")

        ignore_rules = IgnoreRules.from_file(Path(project_path))

        indexed_files = set(self.store.get_all_files())
        current_files: set[str] = set()

        for file_path in self._discover_files(project_path, ignore_rules):
            rel_path = os.path.relpath(file_path, project_path)
            current_files.add(rel_path)
            stats["scanned"] += 1

            parser = self.registry.get_parser(file_path)
            if parser is None:
                continue

            try:
                current_hash = LanguageParser.file_hash(file_path)
            except Exception:
                idx_log.warning("file_hash_error", file=rel_path)
                stats["errors"] += 1
                continue

            stored_hash = self.store.get_file_hash(rel_path)
            if stored_hash == current_hash:
                idx_log.debug("file_skipped", file=rel_path)
                stats["skipped"] += 1
                continue

            try:
                result = self.registry.parse(file_path)
                if result:
                    nodes, edges = result
                    for node in nodes:
                        node.file_path = rel_path
                        if node.kind == NodeKind.FILE:
                            node.qualified_name = rel_path
                        elif node.parent_name:
                            node.qualified_name = f"{rel_path}::{node.parent_name}.{node.name}"
                        else:
                            node.qualified_name = f"{rel_path}::{node.name}"
                    for edge in edges:
                        edge.file_path = rel_path
                        if edge.source.endswith(file_path.split("/")[-1]) or "::" in edge.source:
                            edge.source = edge.source.replace(file_path, rel_path)
                        if edge.target.endswith(file_path.split("/")[-1]) or "::" in edge.target:
                            edge.target = edge.target.replace(file_path, rel_path)

                    self.store.store_file(rel_path, nodes, edges, current_hash)
                    idx_log.info(
                        "file_indexed",
                        file=rel_path,
                        nodes=len(nodes),
                        edges=len(edges),
                    )
                    stats["indexed"] += 1

                    # Generar embeddings semánticos (no-fatal: requiere [search])
                    try:
                        self.store.update_file_embeddings(rel_path)
                    except Exception as emb_err:  # noqa: BLE001
                        idx_log.debug(
                            "embedding_skipped",
                            file=rel_path,
                            reason=str(emb_err),
                        )
                else:
                    idx_log.warning("parse_returned_none", file=rel_path)
                    stats["errors"] += 1
            except Exception:
                idx_log.exception("file_parse_error", file=rel_path)
                stats["errors"] += 1

        for removed in indexed_files - current_files:
            self.store.remove_file(removed)
            idx_log.info("file_removed", file=removed)
            stats["removed"] += 1

        idx_log.info("indexing_finished", **stats)
        return stats

    def _discover_files(self, root_path: str, ignore_rules: IgnoreRules | None = None):
        """Yield absolute paths of source files under *root_path*.

        Directories listed in :attr:`ignore_dirs`, starting with a dot, or
        matching *ignore_rules* are pruned.  Only files whose extension is
        registered in the parser registry are yielded.

        Args:
            root_path: Absolute path to the directory to traverse.
            ignore_rules: Optional :class:`IgnoreRules` loaded from
                ``.codeindexignore``.  When provided, directories and files
                matching its patterns are excluded.

        Yields:
            Absolute file paths for each supported source file found.
        """
        supported = set(self.registry.supported_extensions)
        rules = ignore_rules or IgnoreRules([])
        for dirpath, dirnames, filenames in os.walk(root_path):
            rel_dir = os.path.relpath(dirpath, root_path)
            dirnames[:] = [
                d
                for d in dirnames
                if d not in self.ignore_dirs
                and not d.startswith(".")
                and not rules.is_ignored(os.path.join(rel_dir, d).replace(os.sep, "/").lstrip("./"))
            ]
            for filename in filenames:
                if filename in self.ignore_files:
                    continue
                if Path(filename).suffix not in supported:
                    continue
                rel_file = os.path.relpath(os.path.join(dirpath, filename), root_path).replace(
                    os.sep, "/"
                )
                if rules.is_ignored(rel_file):
                    continue
                yield os.path.join(dirpath, filename)
