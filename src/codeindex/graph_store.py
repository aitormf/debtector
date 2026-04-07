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
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import (
    EdgeInfo,
    GraphEdge,
    GraphNode,
    GraphStats,
    NodeInfo,
)

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
"""


class GraphStore:
    """
    Almacén de grafos de código sobre SQLite.

    Combina almacenamiento relacional persistente con un grafo NetworkX
    en memoria para traversals eficientes. El cache de NetworkX se
    invalida automáticamente tras cada escritura.
    """

    def __init__(self, db_path: str | Path = ".codeindex.db") -> None:
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
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._nxg_cache = None

    def close(self) -> None:
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
            # Limpiar datos previos del archivo
            self._conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
            self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))

            now = time.time()

            # Insertar nodos
            for node in nodes:
                self._conn.execute(
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
        except BaseException:
            self._conn.rollback()
            raise

        self._invalidate_cache()

    def remove_file(self, file_path: str) -> None:
        """Elimina todos los datos de un archivo del índice."""
        self._conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
        self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self._conn.commit()
        self._invalidate_cache()

    def set_metadata(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_metadata(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # ══════════════════════════════════════════
    # LECTURA: Consultas directas (SQL)
    # ══════════════════════════════════════════

    def get_file_hash(self, file_path: str) -> str | None:
        """Devuelve el hash almacenado de un archivo para detectar cambios."""
        row = self._conn.execute(
            "SELECT file_hash FROM nodes WHERE file_path = ? AND kind = 'File' LIMIT 1",
            (file_path,),
        ).fetchone()
        return row["file_hash"] if row and row["file_hash"] else None

    def get_node(self, qualified_name: str) -> GraphNode | None:
        """Busca un nodo por su qualified_name exacto."""
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE qualified_name = ?", (qualified_name,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    def get_nodes_by_file(self, file_path: str) -> list[GraphNode]:
        """Todos los nodos de un archivo."""
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE file_path = ? ORDER BY line_start",
            (file_path,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_all_files(self) -> list[str]:
        """Lista de archivos indexados."""
        rows = self._conn.execute(
            "SELECT DISTINCT file_path FROM nodes WHERE kind = 'File' ORDER BY file_path"
        ).fetchall()
        return [r["file_path"] for r in rows]

    def search_nodes(self, query: str, kind: str | None = None, limit: int = 20) -> list[GraphNode]:
        """
        Búsqueda por palabras clave en nombres de nodos.

        Cada palabra del query debe coincidir (AND lógico).
        Ejemplo: "user service" encuentra "UserService" y "user_service".
        """
        words = query.lower().split()
        if not words:
            return []

        conditions = []
        params: list = []
        for word in words:
            conditions.append("(LOWER(name) LIKE ? OR LOWER(qualified_name) LIKE ?)")
            params.extend([f"%{word}%", f"%{word}%"])

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
        """Encuentra qué archivos importan un módulo dado."""
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
        """Resumen estructural de un archivo: sus nodos y aristas."""
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
        """Aristas que salen de un nodo."""
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
        """Aristas que llegan a un nodo."""
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
        """¿Quién llama a este nodo? (aristas CALLS entrantes)."""
        edges = self.get_incoming(qualified_name, edge_kind="CALLS")
        callers = []
        for e in edges:
            node = self.get_node(e.source_qualified)
            if node:
                callers.append(node)
        return callers

    def callees_of(self, qualified_name: str) -> list[GraphNode]:
        """¿A quién llama este nodo? (aristas CALLS salientes)."""
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
        """
        Análisis de impacto: dado un conjunto de archivos modificados,
        encuentra todos los nodos afectados mediante BFS bidireccional.

        Devuelve:
            changed_nodes: nodos en los archivos cambiados
            impacted_nodes: nodos afectados transitivamente
            impacted_files: archivos impactados
            edges: aristas relevantes
            depth_reached: profundidad alcanzada
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
        """
        Encuentra las cadenas de dependencias de un nodo.
        Devuelve una lista de caminos, cada uno es una lista de qualified_names.

        Útil para responder: "¿de qué depende transitivamente UserService?"
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
        """Estadísticas agregadas del grafo."""
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
        """Construye (o devuelve del cache) el grafo NetworkX en memoria."""
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

    def _batch_get_nodes(self, qualified_names: set[str]) -> list[GraphNode]:
        """Obtiene nodos en lotes para evitar el límite de variables de SQLite."""
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
        """Obtiene aristas donde tanto source como target están en el conjunto."""
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
        return GraphEdge(
            id=row["id"],
            kind=row["kind"],
            source_qualified=row["source_qualified"],
            target_qualified=row["target_qualified"],
            file_path=row["file_path"],
            line=row["line"] or 0,
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )
