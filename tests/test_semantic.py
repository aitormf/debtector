"""Tests para búsqueda semántica con sqlite-vec + fastembed.

Require sqlite-vec instalado; se omiten si no está disponible.
El embedder real (fastembed) se sustituye por una función fake determinista
para evitar descargar el modelo en cada test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.graph_store import GraphStore
from debtector.models import NodeInfo, NodeKind

# Saltar todo el módulo si sqlite-vec no está instalado
sqlite_vec = pytest.importorskip(
    "sqlite_vec", reason="sqlite-vec no instalado; usa: uv add sqlite-vec"
)

# ──────────────────────────────────────────────
# Embedder fake (determinista, sin fastembed)
# ──────────────────────────────────────────────

_DIM = 384


def _unit_vec(idx: int, dim: int = _DIM) -> list[float]:
    """Devuelve un vector unitario con 1.0 en la posición idx % dim."""
    v = [0.0] * dim
    v[idx % dim] = 1.0
    return v


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Embedder fake: mapea texto a vector unitario según keywords."""
    result = []
    for text in texts:
        tl = text.lower()
        if "auth" in tl or "login" in tl or "validate" in tl:
            result.append(_unit_vec(0))
        elif "payment" in tl or "charge" in tl or "billing" in tl:
            result.append(_unit_vec(1))
        elif "health" in tl or "status" in tl or "ping" in tl:
            result.append(_unit_vec(2))
        else:
            result.append(_unit_vec(3))
    return result


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> GraphStore:
    """GraphStore respaldado por archivo temporal."""
    db = tmp_path / ".debtector" / "index.db"
    db.parent.mkdir()
    s = GraphStore(db)
    yield s
    s.close()


def _auth_nodes() -> list[NodeInfo]:
    return [
        NodeInfo(
            kind=NodeKind.FILE,
            name="auth.py",
            qualified_name="src/auth.py",
            file_path="src/auth.py",
        ),
        NodeInfo(
            kind=NodeKind.CLASS,
            name="AuthService",
            qualified_name="src/auth.py::AuthService",
            file_path="src/auth.py",
            docstring="Handles user authentication and login",
        ),
        NodeInfo(
            kind=NodeKind.METHOD,
            name="validate_token",
            qualified_name="src/auth.py::AuthService.validate_token",
            file_path="src/auth.py",
            signature="def validate_token(self, token: str) -> bool",
            docstring="Validate a JWT auth token",
        ),
    ]


def _payment_nodes() -> list[NodeInfo]:
    return [
        NodeInfo(
            kind=NodeKind.FILE,
            name="payment.py",
            qualified_name="src/payment.py",
            file_path="src/payment.py",
        ),
        NodeInfo(
            kind=NodeKind.CLASS,
            name="PaymentGateway",
            qualified_name="src/payment.py::PaymentGateway",
            file_path="src/payment.py",
            docstring="Processes credit card payments and billing",
        ),
        NodeInfo(
            kind=NodeKind.METHOD,
            name="charge",
            qualified_name="src/payment.py::PaymentGateway.charge",
            file_path="src/payment.py",
            signature="def charge(self, amount: float) -> bool",
            docstring="Charge a payment to a credit card",
        ),
    ]


@pytest.fixture()
def populated_store(store: GraphStore) -> GraphStore:
    """Store con nodos de auth y payment, con embeddings generados."""
    store.store_file("src/auth.py", _auth_nodes(), [], "h1")
    store.store_file("src/payment.py", _payment_nodes(), [], "h2")
    store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)
    store.update_file_embeddings("src/payment.py", embed_fn=_fake_embed)
    return store


# ──────────────────────────────────────────────
# Tests: infraestructura
# ──────────────────────────────────────────────


class TestVecInfrastructure:
    """sqlite-vec se carga y la tabla se crea correctamente."""

    def test_vec_available_flag_is_true(self, store: GraphStore) -> None:
        assert store._vec_available is True

    def test_node_embeddings_table_exists(self, store: GraphStore) -> None:
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'node_embeddings'"
        ).fetchone()
        assert row is not None, "La tabla node_embeddings no existe"

    def test_vec_unavailable_flag_can_be_set(
        self, store: GraphStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(store, "_vec_available", False)
        assert store._vec_available is False


# ──────────────────────────────────────────────
# Tests: update_file_embeddings
# ──────────────────────────────────────────────


class TestUpdateFileEmbeddings:
    """update_file_embeddings almacena vectores correctamente."""

    def test_returns_count_of_stored_embeddings(self, store: GraphStore) -> None:
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        count = store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)
        assert count == len(_auth_nodes())

    def test_embeddings_persisted_in_table(self, store: GraphStore) -> None:
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)
        n = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert n == len(_auth_nodes())

    def test_returns_zero_when_vec_unavailable(
        self, store: GraphStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(store, "_vec_available", False)
        count = store.update_file_embeddings("src/x.py", embed_fn=_fake_embed)
        assert count == 0

    def test_returns_zero_when_file_not_indexed(self, store: GraphStore) -> None:
        count = store.update_file_embeddings("no_existe.py", embed_fn=_fake_embed)
        assert count == 0

    def test_reindex_replaces_old_embeddings(self, store: GraphStore) -> None:
        """Al re-indexar un fichero, los embeddings antiguos se sustituyen."""
        # Primera indexación: 3 nodos
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)

        # Segunda indexación: solo 1 nodo
        single_node = [
            NodeInfo(
                kind=NodeKind.CLASS,
                name="AuthService",
                qualified_name="src/auth.py::AuthService",
                file_path="src/auth.py",
                docstring="Handles authentication",
            )
        ]
        store.store_file("src/auth.py", single_node, [], "h2")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)

        n = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert n == 1, f"Esperado 1 embedding tras reindexar, got {n}"

    def test_multiple_files_accumulate(self, store: GraphStore) -> None:
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.store_file("src/payment.py", _payment_nodes(), [], "h2")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)
        store.update_file_embeddings("src/payment.py", embed_fn=_fake_embed)
        n = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert n == len(_auth_nodes()) + len(_payment_nodes())


# ──────────────────────────────────────────────
# Tests: semantic_search
# ──────────────────────────────────────────────


class TestSemanticSearch:
    """semantic_search devuelve resultados ordenados por distancia."""

    def test_returns_list_of_tuples(self, populated_store: GraphStore) -> None:
        results = populated_store.semantic_search("auth", embed_fn=_fake_embed)
        assert isinstance(results, list)
        for item in results:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_results_contain_graph_nodes(self, populated_store: GraphStore) -> None:
        from debtector.models import GraphNode

        results = populated_store.semantic_search("auth", embed_fn=_fake_embed)
        assert all(isinstance(n, GraphNode) for n, _ in results)

    def test_distances_are_non_negative_floats(self, populated_store: GraphStore) -> None:
        results = populated_store.semantic_search("auth", embed_fn=_fake_embed)
        for _, dist in results:
            assert isinstance(dist, float)
            assert dist >= 0.0

    def test_results_ordered_by_ascending_distance(self, populated_store: GraphStore) -> None:
        results = populated_store.semantic_search("auth", embed_fn=_fake_embed, limit=20)
        distances = [d for _, d in results]
        assert distances == sorted(distances)

    def test_auth_query_ranks_auth_nodes_first(self, populated_store: GraphStore) -> None:
        """'auth' debería rankear nodos de autenticación antes que los de pago."""
        results = populated_store.semantic_search("auth login", embed_fn=_fake_embed, limit=20)
        names = [n.name for n, _ in results]
        auth_idx = min(i for i, n in enumerate(names) if n in {"AuthService", "validate_token"})
        payment_idx = min(i for i, n in enumerate(names) if n in {"PaymentGateway", "charge"})
        assert auth_idx < payment_idx, (
            f"Auth ({auth_idx}) no está antes que Payment ({payment_idx})"
        )

    def test_payment_query_ranks_payment_first(self, populated_store: GraphStore) -> None:
        results = populated_store.semantic_search("payment billing", embed_fn=_fake_embed, limit=20)
        names = [n.name for n, _ in results]
        payment_idx = min(i for i, n in enumerate(names) if n in {"PaymentGateway", "charge"})
        auth_idx = min(i for i, n in enumerate(names) if n in {"AuthService", "validate_token"})
        assert payment_idx < auth_idx

    def test_limit_respected(self, populated_store: GraphStore) -> None:
        results = populated_store.semantic_search("auth", embed_fn=_fake_embed, limit=2)
        assert len(results) <= 2

    def test_raises_when_vec_unavailable(
        self, store: GraphStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(store, "_vec_available", False)
        with pytest.raises(RuntimeError, match="sqlite-vec"):
            store.semantic_search("auth", embed_fn=_fake_embed)

    def test_returns_empty_when_no_embeddings(self, store: GraphStore) -> None:
        """Nodes indexados sin embeddings no aparecen en semantic_search."""
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        # No se llama a update_file_embeddings
        results = store.semantic_search("auth", embed_fn=_fake_embed)
        assert results == []


# ──────────────────────────────────────────────
# Tests: limpieza de embeddings
# ──────────────────────────────────────────────


class TestEmbeddingCleanup:
    """Los embeddings se limpian al re-indexar o eliminar archivos."""

    def test_store_file_removes_old_embeddings(self, store: GraphStore) -> None:
        """store_file limpia los embeddings del fichero antes de reinsertar nodos."""
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)

        before = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert before == len(_auth_nodes())

        # Re-indexar: store_file debe limpiar los embeddings de los nodos viejos
        store.store_file("src/auth.py", _auth_nodes()[:1], [], "h2")
        after_store = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        # Los embeddings de los nodos eliminados deben haber desaparecido
        assert after_store == 0

    def test_remove_file_cleans_embeddings(self, store: GraphStore) -> None:
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)

        store.remove_file("src/auth.py")

        n = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert n == 0

    def test_remove_only_target_file_embeddings(self, store: GraphStore) -> None:
        """remove_file no toca los embeddings de otros archivos."""
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        store.store_file("src/payment.py", _payment_nodes(), [], "h2")
        store.update_file_embeddings("src/auth.py", embed_fn=_fake_embed)
        store.update_file_embeddings("src/payment.py", embed_fn=_fake_embed)

        store.remove_file("src/auth.py")

        n = store._conn.execute("SELECT COUNT(*) FROM node_embeddings").fetchone()[0]
        assert n == len(_payment_nodes())


# ──────────────────────────────────────────────
# Tests: get_stats con embeddings
# ──────────────────────────────────────────────


class TestStatsWithEmbeddings:
    """get_stats reporta el número de embeddings cuando vec está disponible."""

    def test_stats_include_embeddings_count(self, populated_store: GraphStore) -> None:
        stats = populated_store.get_stats()
        expected = len(_auth_nodes()) + len(_payment_nodes())
        assert stats.embeddings_count == expected

    def test_stats_embeddings_zero_without_embed_calls(self, store: GraphStore) -> None:
        store.store_file("src/auth.py", _auth_nodes(), [], "h1")
        stats = store.get_stats()
        assert stats.embeddings_count == 0
