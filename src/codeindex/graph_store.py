"""
GraphStore: almacenamiento de grafos de código sobre SQLite.

Un solo archivo .db que almacena:
- Nodos: archivos, clases, funciones, métodos
- Aristas: imports, herencia, llamadas, containment
- Metadatos: versión del schema, timestamps, etc.

Para traversals complejos (impacto, dependencias transitivas) usa
NetworkX como grafo en memoria con cache invalidable.

Uso:
    store = GraphStore(".codeindex.db")
    store.store_file(file_path, nodes, edges, file_hash)
    results = store.search_nodes("UserService")
    impact = store.get_impact_radius(["src/auth.py"])
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from .models import (
    EdgeInfo,
    GraphEdge,
    GraphNode,
    GraphStats,
    NodeInfo,
)

log = structlog.get_logger()

# ──────────────────────────────────────────────
# Schema SQL
# ──────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL UNIQUE,
    file_path       TEXT NOT NULL,
    line_start      INTEGER DEFAULT 0,
    line_end        INTEGER DEFAULT 0,
    language        TEXT DEFAULT '',
    parent_name     TEXT,
    signature       TEXT,
    docstring       TEXT,
    decorators      TEXT DEFAULT '[]',
    file_hash       TEXT DEFAULT '',
    extra           TEXT DEFAULT '{}',
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,
    source_qualified    TEXT NOT NULL,
    target_qualified    TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    line                INTEGER DEFAULT 0,
    extra               TEXT DEFAULT '{}',
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_nodes_qualified ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file_path);

-- FTS5: búsqueda léxica con ranking BM25
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id    UNINDEXED,
    name,
    qualified_name,
    signature,
    docstring,
    tokenize = 'unicode61'
);
"""

# Regex to split camelCase boundaries: "AuthService" → "Auth Service"
_CAMEL_RE = re.compile(r"([a-z])([A-Z])")


class GraphStore:
    """
    Almacén de grafos de código sobre SQLite.

    Combina almacenamiento relacional persistente con un grafo NetworkX
    en memoria para traversals eficientes. El cache de NetworkX se
    invalida automáticamente tras cada escritura.
    """

    def __init__(self, db_path: str | Path = ".codeindex.db") -> None:
        """Initialize the GraphStore and create the SQLite database if needed.

        Args:
            db_path: Path to the SQLite database file. Parent directories are
                created automatically if they do not exist.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        self._init_schema()

        # Cache de NetworkX para traversals
        self._nxg_cache = None
        self._cache_lock = threading.Lock()

    def __enter__(self) -> GraphStore:
        """Support usage as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the database connection on context manager exit."""
        self.close()

    def _init_schema(self) -> None:
        """Execute the DDL script to create tables and indexes if missing."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _invalidate_cache(self) -> None:
        """Discard the cached NetworkX graph so it is rebuilt on next access."""
        with self._cache_lock:
            self._nxg_cache = None

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn:
            self._conn.close()

    # ══════════════════════════════════════════
    # ESCRITURA
    # ══════════════════════════════════════════

    def store_file(
        self,
        file_path: str,
        nodes: list[NodeInfo],
        edges: list[EdgeInfo],
        file_hash: str = "",
    ) -> None:
        """
        Almacena atómicamente todos los nodos y aristas de un archivo.

        Si el archivo ya estaba indexado, elimina sus datos previos y
        los reemplaza. Todo dentro de una transacción: si algo falla,
        no se modifica nada.

        Args:
            file_path: Ruta relativa del archivo.
            nodes: Nodos extraídos por el parser.
            edges: Aristas extraídas por el parser.
            file_hash: SHA-256 del contenido (para detección de cambios).
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # Limpiar FTS antes de borrar nodos (aún necesitamos sus IDs)
            self._conn.execute(
                "DELETE FROM nodes_fts WHERE node_id IN "
                "(SELECT id FROM nodes WHERE file_path = ?)",
                (file_path,),
            )
            # Limpiar datos previos del archivo
            self._conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
            self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))

            now = time.time()

            # Insertar nodos y poblar FTS5
            for node in nodes:
                cur = self._conn.execute(
                    """INSERT INTO nodes
                       (kind, name, qualified_name, file_path, line_start, line_end,
                        language, parent_name, signature, docstring, decorators,
                        file_hash, extra, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(qualified_name) DO UPDATE SET
                         kind=excluded.kind, name=excluded.name,
                         file_path=excluded.file_path,
                         line_start=excluded.line_start, line_end=excluded.line_end,
                         language=excluded.language, parent_name=excluded.parent_name,
                         signature=excluded.signature, docstring=excluded.docstring,
                         decorators=excluded.decorators, file_hash=excluded.file_hash,
                         extra=excluded.extra, updated_at=excluded.updated_at
                    """,
                    (
                        node.kind,
                        node.name,
                        node.qualified_name,
                        node.file_path,
                        node.line_start,
                        node.line_end,
                        node.language,
                        node.parent_name,
                        node.signature,
                        node.docstring,
                        json.dumps(node.decorators),
                        file_hash,
                        json.dumps(node.extra),
                        now,
                    ),
                )
                self._conn.execute(
                    "INSERT INTO nodes_fts"
                    "(node_id, name, qualified_name, signature, docstring)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        cur.lastrowid,
                        self._fts_text(node.name),
                        self._fts_text(node.qualified_name),
                        self._fts_text(node.signature),
                        node.docstring or "",
                    ),
                )

            # Insertar aristas
            for edge in edges:
                self._conn.execute(
                    """INSERT INTO edges
                       (kind, source_qualified, target_qualified, file_path,
                        line, extra, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        edge.kind,
                        edge.source,
                        edge.target,
                        edge.file_path,
                        edge.line,
                        json.dumps(edge.extra),
                        now,
                    ),
                )

            self._conn.commit()
            log.debug(
                "file_stored",
                file=file_path,
                nodes=len(nodes),
                edges=len(edges),
            )
        except BaseException:
            self._conn.rollback()
            raise

        self._invalidate_cache()

    def remove_file(self, file_path: str) -> None:
        """Remove all nodes and edges associated with a file from the index.

        Args:
            file_path: Relative path of the file to remove.
        """
        self._conn.execute(
            "DELETE FROM nodes_fts WHERE node_id IN " "(SELECT id FROM nodes WHERE file_path = ?)",
            (file_path,),
        )
        self._conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
        self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self._conn.commit()
        log.debug("file_removed", file=file_path)
        self._invalidate_cache()

    def set_metadata(self, key: str, value: str) -> None:
        """Persist a key-value pair in the metadata table.

        If the key already exists its value is overwritten.

        Args:
            key: Metadata key (e.g. ``"schema_version"``).
            value: String value to store.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_metadata(self, key: str) -> str | None:
        """Retrieve a value from the metadata table.

        Args:
            key: Metadata key to look up.

        Returns:
            The stored string value, or ``None`` if the key does not exist.
        """
        row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # ══════════════════════════════════════════
    # LECTURA: Consultas directas (SQL)
    # ══════════════════════════════════════════

    def get_file_hash(self, file_path: str) -> str | None:
        """Return the stored SHA-256 hash of a file for change detection.

        Args:
            file_path: Relative path of the file.

        Returns:
            The stored hex-digest string, or ``None`` if the file has not been
            indexed yet.
        """
        row = self._conn.execute(
            "SELECT file_hash FROM nodes WHERE file_path = ? AND kind = 'File' LIMIT 1",
            (file_path,),
        ).fetchone()
        return row["file_hash"] if row and row["file_hash"] else None

    def get_node(self, qualified_name: str) -> GraphNode | None:
        """Look up a single node by its exact qualified name.

        Args:
            qualified_name: Fully-qualified symbol identifier
                (e.g. ``"src/app.py::UserService.get_user"``).

        Returns:
            The matching :class:`GraphNode`, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE qualified_name = ?", (qualified_name,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    def get_nodes_by_file(self, file_path: str) -> list[GraphNode]:
        """Return all nodes that belong to a given file, ordered by line number.

        Args:
            file_path: Relative path of the source file.

        Returns:
            List of :class:`GraphNode` objects sorted by ``line_start``.
        """
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE file_path = ? ORDER BY line_start",
            (file_path,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_all_files(self) -> list[str]:
        """Return the relative paths of all indexed source files.

        Returns:
            Sorted list of file paths currently present in the index.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT file_path FROM nodes WHERE kind = 'File' ORDER BY file_path"
        ).fetchall()
        return [r["file_path"] for r in rows]

    def search_nodes(self, query: str, kind: str | None = None, limit: int = 20) -> list[GraphNode]:
        """Search nodes using FTS5 full-text search with BM25 ranking.

        Splits camelCase and snake_case identifiers at index time so that
        ``"auth"`` matches ``"AuthService"`` and ``"validate"`` matches
        ``"validateEmail"``.  Multi-word queries require ALL words to match
        (AND logic).  Each word is matched as a prefix so ``"serv"`` finds
        ``"service"``.

        Falls back to SQL ``LIKE`` search when the FTS5 table is unavailable.

        Args:
            query: Free-text search string (e.g. ``"auth service"``,
                ``"create user"``).
            kind: Optional :class:`~codeindex.models.NodeKind` string to filter
                results (e.g. ``"Class"``, ``"Method"``).
            limit: Maximum number of results to return. Defaults to 20.

        Returns:
            List of matching :class:`GraphNode` objects ordered by BM25
            relevance, up to *limit* items.
        """
        words = query.strip().split()
        if not words:
            return []
        try:
            return self._search_fts(words, kind, limit)
        except sqlite3.OperationalError:
            return self._search_like(words, kind, limit)

    def _search_fts(self, words: list[str], kind: str | None, limit: int) -> list[GraphNode]:
        """Execute an FTS5 MATCH query with BM25 ranking.

        Args:
            words: Tokenised search terms (already split on whitespace).
            kind: Optional node kind filter.
            limit: Maximum results.

        Returns:
            Ranked list of :class:`GraphNode` objects.
        """
        # Normalise the query the same way as the indexed content (camelCase split,
        # non-word → space), then add prefix wildcard to each resulting token.
        normalised = self._fts_text(*words)
        fts_expr = " ".join(w + "*" for w in normalised.split() if w)
        if not fts_expr:
            return []

        kind_clause = "AND n.kind = ?" if kind else ""
        params: list[Any] = [fts_expr]
        if kind:
            params.append(kind)
        params.append(limit)

        rows = self._conn.execute(
            f"""SELECT n.* FROM (
                    SELECT node_id, rank FROM nodes_fts
                    WHERE nodes_fts MATCH ?
                    ORDER BY rank
                ) fts
                JOIN nodes n ON n.id = fts.node_id
                {kind_clause}
                ORDER BY fts.rank
                LIMIT ?""",  # nosec B608
            params,
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def _search_like(self, words: list[str], kind: str | None, limit: int) -> list[GraphNode]:
        """Fallback SQL LIKE search used when FTS5 is unavailable.

        Args:
            words: Tokenised search terms.
            kind: Optional node kind filter.
            limit: Maximum results.

        Returns:
            List of :class:`GraphNode` objects (unranked).
        """
        conditions: list[str] = []
        params: list[Any] = []
        for word in words:
            w = word.lower()
            conditions.append("(LOWER(name) LIKE ? OR LOWER(qualified_name) LIKE ?)")
            params.extend([f"%{w}%", f"%{w}%"])
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM nodes WHERE {where} LIMIT ?",  # nosec B608
            params,
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def search_imports(self, module: str) -> list[dict]:
        """Find all files that import a given module (partial match).

        Args:
            module: Module name or substring to search for
                (e.g. ``"flask"``, ``"auth.utils"``).

        Returns:
            List of dicts with keys ``source_qualified``, ``target_qualified``,
            ``file_path``, and ``line``.
        """
        rows = self._conn.execute(
            """SELECT e.source_qualified, e.target_qualified, e.file_path, e.line
               FROM edges e
               WHERE e.kind = 'IMPORTS_FROM'
                 AND e.target_qualified LIKE ?
               ORDER BY e.file_path""",
            (f"%{module}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_file_summary(self, file_path: str) -> dict | None:
        """Return a structured summary of a file's symbols and relationships.

        Args:
            file_path: Relative path of the source file.

        Returns:
            Dict with keys ``path``, ``language``, ``nodes`` (list of symbol
            dicts), and ``edges`` (list of relationship dicts).  Returns
            ``None`` if the file has not been indexed.
        """
        nodes = self.get_nodes_by_file(file_path)
        if not nodes:
            return None

        edges = self._conn.execute(
            "SELECT * FROM edges WHERE file_path = ? ORDER BY line",
            (file_path,),
        ).fetchall()

        return {
            "path": file_path,
            "language": nodes[0].language if nodes else "",
            "nodes": [
                {
                    "kind": n.kind,
                    "name": n.name,
                    "signature": n.signature,
                    "line_start": n.line_start,
                    "line_end": n.line_end,
                    "parent": n.parent_name,
                }
                for n in nodes
                if n.kind != "File"
            ],
            "edges": [
                {
                    "kind": e["kind"],
                    "source": e["source_qualified"],
                    "target": e["target_qualified"],
                }
                for e in edges
            ],
        }

    # ══════════════════════════════════════════
    # LECTURA: Consultas de grafo (NetworkX)
    # ══════════════════════════════════════════

    def get_outgoing(self, qualified_name: str, edge_kind: str | None = None) -> list[GraphEdge]:
        """Return edges that originate from the given node.

        Args:
            qualified_name: Source node identifier.
            edge_kind: Optional :class:`~codeindex.models.EdgeKind` to filter
                by (e.g. ``"IMPORTS_FROM"``).

        Returns:
            List of :class:`GraphEdge` objects leaving the node.
        """
        if edge_kind:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE source_qualified = ? AND kind = ?",
                (qualified_name, edge_kind),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE source_qualified = ?",
                (qualified_name,),
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_incoming(self, qualified_name: str, edge_kind: str | None = None) -> list[GraphEdge]:
        """Return edges that point to the given node.

        Args:
            qualified_name: Target node identifier.
            edge_kind: Optional :class:`~codeindex.models.EdgeKind` to filter
                by (e.g. ``"CALLS"``).

        Returns:
            List of :class:`GraphEdge` objects arriving at the node.
        """
        if edge_kind:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE target_qualified = ? AND kind = ?",
                (qualified_name, edge_kind),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE target_qualified = ?",
                (qualified_name,),
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def callers_of(self, qualified_name: str) -> list[GraphNode]:
        """Return all nodes that call the given symbol (inbound CALLS edges).

        Args:
            qualified_name: Target symbol identifier.

        Returns:
            List of :class:`GraphNode` objects that call *qualified_name*.
            Empty when no CALLS edges have been indexed yet.
        """
        edges = self.get_incoming(qualified_name, edge_kind="CALLS")
        callers = []
        for e in edges:
            node = self.get_node(e.source_qualified)
            if node:
                callers.append(node)
        return callers

    def callees_of(self, qualified_name: str) -> list[GraphNode]:
        """Return all nodes called by the given symbol (outbound CALLS edges).

        Args:
            qualified_name: Source symbol identifier.

        Returns:
            List of :class:`GraphNode` objects called by *qualified_name*.
            Empty when no CALLS edges have been indexed yet.
        """
        edges = self.get_outgoing(qualified_name, edge_kind="CALLS")
        callees = []
        for e in edges:
            node = self.get_node(e.target_qualified)
            if node:
                callees.append(node)
        return callees

    def get_impact_radius(
        self,
        changed_files: list[str],
        max_depth: int = 2,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """Compute the impact radius of a set of changed files using bidirectional BFS.

        Args:
            changed_files: Relative paths of files that were modified.
            max_depth: Maximum number of hops to traverse. Defaults to 2.
            max_nodes: Safety cap on total nodes visited. Defaults to 500.

        Returns:
            Dict with keys:

            * ``changed_nodes`` – :class:`GraphNode` list for the changed files.
            * ``impacted_nodes`` – :class:`GraphNode` list of transitively affected nodes.
            * ``impacted_files`` – Deduplicated list of affected file paths.
            * ``edges`` – Relevant :class:`GraphEdge` list connecting the above nodes.
            * ``depth_reached`` – Actual BFS depth reached.
        """
        nxg = self._build_networkx_graph()

        # Semillas: todos los qualified_names en archivos cambiados
        seeds: set[str] = set()
        for f in changed_files:
            for node in self.get_nodes_by_file(f):
                seeds.add(node.qualified_name)

        # BFS bidireccional
        visited: set[str] = set()
        frontier = seeds.copy()
        impacted: set[str] = set()
        depth = 0

        while frontier and depth < max_depth:
            visited.update(frontier)
            next_frontier: set[str] = set()

            for qn in frontier:
                if qn in nxg:
                    # Hacia adelante: ¿qué afecta este nodo?
                    for neighbor in nxg.neighbors(qn):
                        if neighbor not in visited:
                            next_frontier.add(neighbor)
                            impacted.add(neighbor)
                    # Hacia atrás: ¿quién depende de este nodo?
                    for pred in nxg.predecessors(qn):
                        if pred not in visited:
                            next_frontier.add(pred)
                            impacted.add(pred)

            next_frontier -= visited
            if len(visited) + len(next_frontier) > max_nodes:
                break
            frontier = next_frontier
            depth += 1

        # Construir resultado
        changed_nodes = self._batch_get_nodes(seeds)
        impacted_nodes = self._batch_get_nodes(impacted - seeds)
        impacted_files = list({n.file_path for n in impacted_nodes})

        all_qns = seeds | {n.qualified_name for n in impacted_nodes}
        relevant_edges = self._get_edges_among(all_qns)

        return {
            "changed_nodes": changed_nodes,
            "impacted_nodes": impacted_nodes,
            "impacted_files": impacted_files,
            "edges": relevant_edges,
            "depth_reached": depth,
        }

    def get_dependency_chain(self, qualified_name: str, max_depth: int = 5) -> list[list[str]]:
        """Find all dependency chains reachable from a node using DFS.

        Useful for answering "what does UserService transitively depend on?".

        Args:
            qualified_name: Starting node identifier.
            max_depth: Maximum chain length to explore. Defaults to 5.

        Returns:
            List of paths, where each path is a list of qualified_name strings
            beginning at *qualified_name* and following outbound edges.
        """
        nxg = self._build_networkx_graph()
        if qualified_name not in nxg:
            return []

        chains = []
        visited = {qualified_name}

        def _dfs(current: str, path: list[str], depth: int):
            if depth >= max_depth:
                return
            if current in nxg:
                for neighbor in nxg.neighbors(current):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        new_path = path + [neighbor]
                        chains.append(new_path)
                        _dfs(neighbor, new_path, depth + 1)

        _dfs(qualified_name, [qualified_name], 0)
        return chains

    # ══════════════════════════════════════════
    # ESTADÍSTICAS
    # ══════════════════════════════════════════

    def get_stats(self) -> GraphStats:
        """Return aggregate statistics for the current index.

        Returns:
            A :class:`~codeindex.models.GraphStats` instance with total node
            and edge counts, per-kind breakdowns, language list, and file count.
        """
        total_nodes = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        total_edges = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        nodes_by_kind = {}
        for row in self._conn.execute("SELECT kind, COUNT(*) as cnt FROM nodes GROUP BY kind"):
            nodes_by_kind[row["kind"]] = row["cnt"]

        edges_by_kind = {}
        for row in self._conn.execute("SELECT kind, COUNT(*) as cnt FROM edges GROUP BY kind"):
            edges_by_kind[row["kind"]] = row["cnt"]

        languages = [
            r["language"]
            for r in self._conn.execute(
                "SELECT DISTINCT language FROM nodes WHERE language != '' AND language IS NOT NULL"
            )
        ]

        files_count = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'File'"
        ).fetchone()[0]

        return GraphStats(
            total_nodes=total_nodes,
            total_edges=total_edges,
            nodes_by_kind=nodes_by_kind,
            edges_by_kind=edges_by_kind,
            languages=languages,
            files_count=files_count,
        )

    # ══════════════════════════════════════════
    # INTERNALS
    # ══════════════════════════════════════════

    def _build_networkx_graph(self):
        """Build (or return cached) the in-memory NetworkX DiGraph.

        All edges from the database are loaded into a directed graph used for
        BFS/DFS traversals. The result is cached until the next write.
        """
        with self._cache_lock:
            if self._nxg_cache is not None:
                return self._nxg_cache

            import networkx as nx

            g = nx.DiGraph()

            rows = self._conn.execute("SELECT * FROM edges").fetchall()
            for r in rows:
                g.add_edge(
                    r["source_qualified"],
                    r["target_qualified"],
                    kind=r["kind"],
                )

            self._nxg_cache = g
            return g

    @staticmethod
    def _fts_text(*parts: str | None) -> str:
        """Normalise text for FTS5 indexing.

        Splits camelCase boundaries, replaces non-word characters with spaces,
        and lowercases the result so that tokens like ``"AuthService"`` become
        ``"auth service"`` and are individually searchable.

        Args:
            *parts: One or more strings to combine (``None`` values are skipped).

        Returns:
            A single lowercased, space-separated string ready for FTS5 insertion.
        """
        combined = " ".join(p for p in parts if p)
        # Split camelCase: "AuthService" → "Auth Service"
        split = _CAMEL_RE.sub(r"\1 \2", combined)
        # Replace non-word chars with spaces in both versions
        split = re.sub(r"[^\w]+", " ", split)
        # Also keep original (non-split) so "authservice" finds "AuthService"
        original = re.sub(r"[^\w]+", " ", combined)
        return f"{split} {original}".lower().strip()

    def _batch_get_nodes(self, qualified_names: set[str]) -> list[GraphNode]:
        """Fetch nodes by qualified_name in batches of 450 to stay under SQLite's variable limit."""
        if not qualified_names:
            return []
        results = []
        qns = list(qualified_names)
        batch_size = 450
        for i in range(0, len(qns), batch_size):
            batch = qns[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"SELECT * FROM nodes WHERE qualified_name IN ({placeholders})",  # nosec B608
                batch,
            ).fetchall()
            results.extend(self._row_to_node(r) for r in rows)
        return results

    def _get_edges_among(self, qualified_names: set[str]) -> list[GraphEdge]:
        """Fetch edges whose source AND target are both within the given node set."""
        if not qualified_names:
            return []
        results = []
        qns = list(qualified_names)
        batch_size = 450
        for i in range(0, len(qns), batch_size):
            batch = qns[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"SELECT * FROM edges WHERE source_qualified IN ({placeholders})",  # nosec B608
                batch,
            ).fetchall()
            for r in rows:
                edge = self._row_to_edge(r)
                if edge.target_qualified in qualified_names:
                    results.append(edge)
        return results

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        """Convert a raw SQLite row into a :class:`GraphNode` dataclass."""
        return GraphNode(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            qualified_name=row["qualified_name"],
            file_path=row["file_path"],
            line_start=row["line_start"] or 0,
            line_end=row["line_end"] or 0,
            language=row["language"] or "",
            parent_name=row["parent_name"],
            signature=row["signature"],
            docstring=row["docstring"],
            file_hash=row["file_hash"],
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )

    def _row_to_edge(self, row: sqlite3.Row) -> GraphEdge:
        """Convert a raw SQLite row into a :class:`GraphEdge` dataclass."""
        return GraphEdge(
            id=row["id"],
            kind=row["kind"],
            source_qualified=row["source_qualified"],
            target_qualified=row["target_qualified"],
            file_path=row["file_path"],
            line=row["line"] or 0,
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )
