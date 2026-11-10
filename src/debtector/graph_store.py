"""
GraphStore: code graph storage on top of SQLite.

A single .db file that stores:
- Nodes: files, classes, functions, methods
- Edges: imports, inheritance, calls, containment
- Metadata: schema version, timestamps, etc.

For complex traversals (impact, transitive dependencies) it uses
NetworkX as an in-memory graph with an invalidatable cache.

Usage:
    store = GraphStore(".debtector.db")
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
from collections import defaultdict
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
# Schema versioning
# ──────────────────────────────────────────────

CURRENT_SCHEMA_VERSION: int = 1
"""Version number of the current database schema.

Increment this constant and add an entry to :data:`_MIGRATION_SQL` whenever a
breaking or additive schema change is introduced.
"""


class SchemaTooNewError(RuntimeError):
    """Raised when the stored schema version exceeds :data:`CURRENT_SCHEMA_VERSION`.

    This usually means the database was created by a newer version of
    debtector and cannot be safely opened by this version.
    """


# SQL to apply for each schema upgrade step.
# Key = target version number.  The corresponding SQL is run *after* the base
# schema (_SCHEMA_SQL) has been applied with IF NOT EXISTS guards, so only the
# *delta* needs to be expressed here.
#
# v1 is the baseline: no DDL delta is needed; only version tracking is added.
# Example of a future migration:
#   2: "ALTER TABLE nodes ADD COLUMN foo TEXT DEFAULT '';",
_MIGRATION_SQL: dict[int, str] = {}

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

-- Indexes for frequent queries
CREATE INDEX IF NOT EXISTS idx_nodes_qualified ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_qualified);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file_path);

-- FTS5: lexical search with BM25 ranking
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
    Code graph store on top of SQLite.

    Combines persistent relational storage with an in-memory NetworkX
    graph for efficient traversals. The NetworkX cache is automatically
    invalidated after every write.
    """

    def __init__(self, db_path: str | Path = ".debtector.db") -> None:
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

        # ``test_paths`` directories (relative to the indexed root, with a
        # trailing "/") that count as tests in addition to the conventions.
        self.test_prefixes: list[str] = []

        # NetworkX cache for traversals
        self._nxg_cache = None
        self._cache_lock = threading.Lock()

    def __enter__(self) -> GraphStore:
        """Support usage as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the database connection on context manager exit."""
        self.close()

    def _init_schema(self) -> None:
        """Execute the DDL script and apply any pending schema migrations."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """Check the stored schema version and apply pending migrations in order.

        Reads ``schema_version`` from the ``metadata`` table.  A missing entry
        is treated as version 0 (legacy database created before versioning was
        introduced).

        Raises:
            SchemaTooNewError: If the stored version exceeds
                :data:`CURRENT_SCHEMA_VERSION`.
        """
        raw = self.get_metadata("schema_version")
        stored = int(raw) if raw is not None else 0

        if stored > CURRENT_SCHEMA_VERSION:
            raise SchemaTooNewError(
                f"Database schema version {stored} is newer than the supported "
                f"version {CURRENT_SCHEMA_VERSION}. Please upgrade debtector."
            )

        for target in range(stored + 1, CURRENT_SCHEMA_VERSION + 1):
            migration_sql = _MIGRATION_SQL.get(target)
            if migration_sql:
                # executescript issues an implicit COMMIT before running; that
                # is acceptable here since schema changes cannot be rolled back
                # in SQLite anyway.
                self._conn.executescript(migration_sql)
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(target)),
            )
            self._conn.commit()
            log.info("schema_migrated", from_version=target - 1, to_version=target)

    def _invalidate_cache(self) -> None:
        """Discard the cached NetworkX graph so it is rebuilt on next access."""
        with self._cache_lock:
            self._nxg_cache = None

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn:
            self._conn.close()

    # ══════════════════════════════════════════
    # WRITES
    # ══════════════════════════════════════════

    def store_file(
        self,
        file_path: str,
        nodes: list[NodeInfo],
        edges: list[EdgeInfo],
        file_hash: str = "",
    ) -> None:
        """
        Atomically store all nodes and edges of a file.

        If the file was already indexed, its previous data is removed and
        replaced. Everything runs inside one transaction: if anything
        fails, nothing is modified.

        Args:
            file_path: Relative path of the file.
            nodes: Nodes extracted by the parser.
            edges: Edges extracted by the parser.
            file_hash: SHA-256 of the content (for change detection).
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # Clean FTS before deleting nodes (we still need their IDs)
            self._conn.execute(
                "DELETE FROM nodes_fts WHERE node_id IN (SELECT id FROM nodes WHERE file_path = ?)",
                (file_path,),
            )
            # Clean the file's previous data
            self._conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
            self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))

            now = time.time()

            # Insert nodes and populate FTS5
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

            # Insert edges
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
        """Remove all nodes and edges associated with a file.

        Args:
            file_path: Relative path of the file to remove.
        """
        self._conn.execute(
            "DELETE FROM nodes_fts WHERE node_id IN (SELECT id FROM nodes WHERE file_path = ?)",
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
    # READS: direct queries (SQL)
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

    def get_nodes_by_kind(self, kind: str) -> list[GraphNode]:
        """Return every node of a given kind across all files.

        Args:
            kind: Node kind (a :class:`NodeKind` value, e.g. ``NodeKind.CLASS``).

        Returns:
            List of :class:`GraphNode` objects ordered by file path and line number.
        """
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE kind = ? ORDER BY file_path, line_start",
            (kind,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

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
            kind: Optional :class:`~debtector.models.NodeKind` string to filter
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
    # READS: graph queries (NetworkX)
    # ══════════════════════════════════════════

    def get_outgoing(self, qualified_name: str, edge_kind: str | None = None) -> list[GraphEdge]:
        """Return edges that originate from the given node.

        Args:
            qualified_name: Source node identifier.
            edge_kind: Optional :class:`~debtector.models.EdgeKind` to filter
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
            edge_kind: Optional :class:`~debtector.models.EdgeKind` to filter
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

        # Seeds: all qualified_names in changed files
        seeds: set[str] = set()
        for f in changed_files:
            for node in self.get_nodes_by_file(f):
                seeds.add(node.qualified_name)

        # Bidirectional BFS
        visited: set[str] = set()
        frontier = seeds.copy()
        impacted: set[str] = set()
        depth = 0

        while frontier and depth < max_depth:
            visited.update(frontier)
            next_frontier: set[str] = set()

            for qn in frontier:
                if qn in nxg:
                    # Forward: what does this node affect?
                    for neighbor in nxg.neighbors(qn):
                        if neighbor not in visited:
                            next_frontier.add(neighbor)
                            impacted.add(neighbor)
                    # Backward: who depends on this node?
                    for pred in nxg.predecessors(qn):
                        if pred not in visited:
                            next_frontier.add(pred)
                            impacted.add(pred)

            next_frontier -= visited
            if len(visited) + len(next_frontier) > max_nodes:
                break
            frontier = next_frontier
            depth += 1

        # Build result
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
    # STATISTICS
    # ══════════════════════════════════════════
    # COVERS: test coverage edges
    # ══════════════════════════════════════════

    # Path/name conventions that identify test files, as LIKE patterns.
    #
    # NOTE: the ``tests/`` prefix patterns here are intentionally broader than
    # ``is_test_file()`` in utils.py.  ``is_test_file()`` inspects only the
    # filename; this SQL also catches helpers and fixtures living inside a
    # ``tests/`` directory (e.g. ``tests/helpers.py``) which should not be
    # considered production symbols.
    #
    # ``../%`` matches files outside the index root: the indexer only stores
    # those when they come from ``test_paths`` in ``debtector.toml``.
    # LIKE patterns with ``\`` as escape char: ``\_`` is a literal underscore
    # (an unescaped ``_`` would match any character, e.g. ``testrisk.py``).
    _TEST_FILE_PATTERNS = (
        "test\\_%",
        "%/test\\_%",
        "%\\_test.py",
        "%.test.ts",
        "%.test.js",
        "%.spec.ts",
        "%.spec.js",
        "tests/%",
        "%/tests/%",
        "../%",
    )

    @staticmethod
    def _like_to_regex(pattern: str) -> re.Pattern[str]:
        """Translate a LIKE pattern (``%``, ``\\`` escape) into a compiled regex."""
        out = []
        it = iter(pattern)
        for ch in it:
            if ch == "\\":
                out.append(re.escape(next(it, "\\")))
            elif ch == "%":
                out.append(".*")
            else:
                out.append(re.escape(ch))
        return re.compile("".join(out), re.DOTALL)

    def is_test_path(self, file_path: str) -> bool:
        """Return whether *file_path* (relative to the index root) is a test file.

        Same classification as the SQL predicate of :meth:`_test_file_clause`:
        path conventions plus ``test_prefixes``.  The indexer passes the result
        to the parsers so they emit the CALLS edges that become COVERS edges.

        Args:
            file_path: POSIX path relative to the index root.

        Returns:
            ``True`` for test files.
        """
        if any(file_path.startswith(prefix) for prefix in self.test_prefixes):
            return True
        return any(self._like_to_regex(p).fullmatch(file_path) for p in self._TEST_FILE_PATTERNS)

    def _test_file_clause(self, alias: str = "n") -> tuple[str, list[str | int]]:
        """Build the SQL predicate that identifies test files.

        Combines the path conventions with ``self.test_prefixes`` (directories
        from ``test_paths``, relative to the index root).

        Args:
            alias: Alias of the ``nodes`` table in the surrounding query.

        Returns:
            Tuple ``(sql, params)``; *sql* is a parenthesised boolean expression.
        """
        col = f"{alias}.file_path"
        parts = [f"{col} LIKE '{p}' ESCAPE '\\'" for p in self._TEST_FILE_PATTERNS]
        params: list[str | int] = []
        for prefix in self.test_prefixes:
            # prefix is "" for the root itself, otherwise "dir/" (trailing slash).
            parts.append(f"substr({col}, 1, ?) = ?")
            params.extend([len(prefix), prefix])
        return "(" + " OR ".join(parts) + ")", params

    def count_test_files(self) -> int:
        """Count indexed File nodes that are test files.

        Returns:
            Number of File nodes matching the test conventions or ``test_paths``.
        """
        clause, params = self._test_file_clause("n")
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM nodes n WHERE n.kind = 'File' AND {clause}",  # nosec B608
            params,
        ).fetchone()
        return int(row[0])

    # Batch size for IN (...) queries — stays well below SQLite's 999-variable limit.
    _BATCH_SIZE = 450

    def update_covers_edges(self) -> int:
        """Rebuild all COVERS edges from unresolved CALLS edges in test files.

        A COVERS edge ``test_fn → prod_fn`` is created for every unresolved
        CALLS edge (``extra`` contains ``"unresolved": true``) whose source
        lives in a test file and whose bare target name matches a production
        node (Function or Method) in a non-test file.

        This method is idempotent: it deletes all existing COVERS edges before
        re-deriving them.

        Returns:
            Number of COVERS edges created.
        """
        self._conn.execute("DELETE FROM edges WHERE kind = 'COVERS'")

        # Unresolved CALLS from test functions toward bare names.
        # The JOIN aliases the nodes table as src_n.
        src_clause, src_params = self._test_file_clause("src_n")
        unresolved = self._conn.execute(
            f"""
            SELECT e.source_qualified, e.target_qualified AS raw_name, e.file_path, e.line
            FROM edges e
            JOIN nodes src_n ON src_n.qualified_name = e.source_qualified
            WHERE e.kind = 'CALLS'
              AND e.extra LIKE '%"unresolved"%'
              AND {src_clause}
            """,  # nosec B608 — clause built from class constants and placeholders
            src_params,
        ).fetchall()

        if not unresolved:
            self._conn.commit()
            return 0

        # Batch-resolve raw names → production qualified_names to avoid N+1 queries.
        # Build a lookup: raw_name → list of (source_qualified, file_path, line)
        callers_by_name: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for row in unresolved:
            callers_by_name[row["raw_name"]].append(
                (row["source_qualified"], row["file_path"], row["line"])
            )

        distinct_names = list(callers_by_name.keys())
        prod_clause, prod_params = self._test_file_clause("n")
        now = time.time()
        count = 0
        inserts: list[tuple] = []

        # Process in batches of _BATCH_SIZE to respect SQLite's variable limit.
        for i in range(0, len(distinct_names), self._BATCH_SIZE):
            batch = distinct_names[i : i + self._BATCH_SIZE]
            placeholders = ",".join("?" * len(batch))
            prod_rows = self._conn.execute(
                f"""
                SELECT n.name, n.qualified_name FROM nodes n
                WHERE n.name IN ({placeholders})
                  AND n.kind IN ('Function', 'Method')
                  AND NOT {prod_clause}
                """,  # nosec B608 — only placeholders and class constants
                [*batch, *prod_params],
            ).fetchall()

            for prod in prod_rows:
                for source_qn, file_path, line in callers_by_name[prod["name"]]:
                    inserts.append((source_qn, prod["qualified_name"], file_path, line, now))
                    count += 1

        self._conn.executemany(
            """
            INSERT OR IGNORE INTO edges
              (kind, source_qualified, target_qualified, file_path, line, extra, updated_at)
            VALUES ('COVERS', ?, ?, ?, ?, '{}', ?)
            """,
            inserts,
        )
        self._conn.commit()
        self._invalidate_cache()
        log.info("covers_edges_updated", count=count)
        return count

    def get_uncovered_symbols(self, path_filter: str | None = None) -> list[GraphNode]:
        """Return Function and Method nodes in production files with no COVERS edge.

        Test files are excluded from the results.  An optional path filter
        restricts results to a single file or directory prefix.

        Args:
            path_filter: If given, only symbols whose ``file_path`` starts with
                this string are returned (e.g. ``"src/auth.py"`` or ``"src/"``).

        Returns:
            List of :class:`~debtector.models.GraphNode` instances that have no
            incoming COVERS edge.
        """
        clause, params = self._test_file_clause("n")
        query = f"""
            SELECT n.* FROM nodes n
            WHERE n.kind IN ('Function', 'Method')
              AND NOT {clause}
              AND n.qualified_name NOT IN (
                SELECT target_qualified FROM edges WHERE kind = 'COVERS'
              )
        """  # nosec B608 — clause built from class constants and placeholders

        if path_filter:
            query += " AND n.file_path LIKE ?"
            params.append(f"{path_filter}%")

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ══════════════════════════════════════════

    def get_untested_files(self) -> set[str]:
        """Return production files where no Function or Method has a COVERS edge.

        Files without functions or methods (e.g. only constants) are never
        reported: there is nothing in them a test could cover.

        Returns:
            Set of ``file_path`` values.
        """
        clause, params = self._test_file_clause("n")
        query = f"""
            SELECT n.file_path FROM nodes n
            WHERE n.kind IN ('Function', 'Method')
              AND NOT {clause}
            GROUP BY n.file_path
            HAVING SUM(
                n.qualified_name IN (SELECT target_qualified FROM edges WHERE kind = 'COVERS')
            ) = 0
        """  # nosec B608 — clause built from class constants and placeholders
        return {r["file_path"] for r in self._conn.execute(query, params).fetchall()}

    def count_external_nodes(self, kind: str) -> int:
        """Count nodes of *kind* stored outside the index root (``../`` paths).

        These come only from ``test_paths`` that lie outside the indexed directory.

        Args:
            kind: Node kind, e.g. ``"File"`` or ``"Class"``.

        Returns:
            Number of matching nodes.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = ? AND file_path LIKE '../%'", (kind,)
        ).fetchone()
        return int(row[0])

    def get_stats(self) -> GraphStats:
        """Return aggregate statistics for the current index.

        Returns:
            A :class:`~debtector.models.GraphStats` instance with total node
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

    def _batch_get_nodes_by_id(self, node_ids: set[int]) -> list[GraphNode]:
        """Fetch nodes by their integer primary key in batches of 450.

        Args:
            node_ids: Set of ``nodes.id`` values to retrieve.

        Returns:
            List of :class:`GraphNode` objects (order not guaranteed).
        """
        if not node_ids:
            return []
        results = []
        ids = list(node_ids)
        batch_size = 450
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({placeholders})",  # nosec B608
                batch,
            ).fetchall()
            results.extend(self._row_to_node(r) for r in rows)
        return results

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
