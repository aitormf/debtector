"""
Indexador principal: conecta parsers con el GraphStore.

Recorre el proyecto, detecta archivos nuevos/modificados, los parsea
con Tree-sitter y almacena los nodos y aristas en el GraphStore.
"""

from __future__ import annotations

import os
from pathlib import Path

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
        self.store = store
        self.registry = ParserRegistry()
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.ignore_files = ignore_files or DEFAULT_IGNORE_FILES

    def index(self, project_path: str) -> dict:
        """
        Indexa un proyecto completo con detección de cambios.

        Returns:
            {"scanned": N, "indexed": N, "skipped": N, "errors": N, "removed": N}
        """
        project_path = os.path.abspath(project_path)
        stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0, "removed": 0}
        idx_log = log.bind(project=project_path)
        idx_log.info("indexing_started")

        indexed_files = set(self.store.get_all_files())
        current_files: set[str] = set()

        for file_path in self._discover_files(project_path):
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

    def _discover_files(self, root_path: str):
        supported = set(self.registry.supported_extensions)
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [
                d for d in dirnames if d not in self.ignore_dirs and not d.startswith(".")
            ]
            for filename in filenames:
                if filename in self.ignore_files:
                    continue
                if Path(filename).suffix in supported:
                    yield os.path.join(dirpath, filename)
