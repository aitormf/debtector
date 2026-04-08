"""Tests for FTS5 full-text search in GraphStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.graph_store import GraphStore
from codeindex.models import NodeInfo, NodeKind


@pytest.fixture()
def store(tmp_path: Path) -> GraphStore:
    """GraphStore backed by a temp file."""
    db = tmp_path / ".codeindex" / "index.db"
    db.parent.mkdir()
    s = GraphStore(db)
    yield s
    s.close()


def _make_nodes(*specs) -> list[NodeInfo]:
    """Helper: create NodeInfo from (kind, name, file, signature, docstring) tuples."""
    nodes = []
    for kind, name, file, sig, doc in specs:
        nodes.append(
            NodeInfo(
                kind=kind,
                name=name,
                qualified_name=f"{file}::{name}" if kind != NodeKind.FILE else file,
                file_path=file,
                signature=sig,
                docstring=doc,
            )
        )
    return nodes


@pytest.fixture()
def populated_store(store: GraphStore) -> GraphStore:
    """Store with a small set of nodes covering camelCase, snake_case, and docstrings."""
    nodes = _make_nodes(
        (NodeKind.FILE, "auth.py", "src/auth.py", None, None),
        (
            NodeKind.CLASS,
            "AuthService",
            "src/auth.py",
            "class AuthService",
            "Handles user authentication",
        ),
        (
            NodeKind.METHOD,
            "validateEmail",
            "src/auth.py",
            "def validateEmail(self)",
            "Validates email format",
        ),
        (
            NodeKind.METHOD,
            "create_user",
            "src/auth.py",
            "def create_user(self)",
            "Creates a new user account",
        ),
        (NodeKind.FILE, "payment.py", "src/payment.py", None, None),
        (
            NodeKind.CLASS,
            "PaymentGateway",
            "src/payment.py",
            "class PaymentGateway",
            "Processes credit card payments",
        ),
        (
            NodeKind.METHOD,
            "charge",
            "src/payment.py",
            "def charge(self, amount)",
            "Charge a credit card",
        ),
        (
            NodeKind.FUNCTION,
            "health_check",
            "src/payment.py",
            "def health_check()",
            "Returns service health status",
        ),
    )
    store.store_file("src/auth.py",    nodes[:4], [], "hash1")
    store.store_file("src/payment.py", nodes[4:], [], "hash2")
    return store


# ──────────────────────────────────────────────
# Basic FTS functionality
# ──────────────────────────────────────────────


class TestFTSBasic:
    """FTS5 finds nodes by exact name and substring."""

    def test_finds_exact_name(self, populated_store: GraphStore) -> None:
        results = populated_store.search_nodes("AuthService")
        names = [n.name for n in results]
        assert "AuthService" in names

    def test_finds_by_lowercase(self, populated_store: GraphStore) -> None:
        results = populated_store.search_nodes("authservice")
        names = [n.name for n in results]
        assert "AuthService" in names

    def test_empty_query_returns_empty(self, populated_store: GraphStore) -> None:
        assert populated_store.search_nodes("") == []

    def test_nonexistent_returns_empty(self, populated_store: GraphStore) -> None:
        assert populated_store.search_nodes("xyznonexistent") == []


# ──────────────────────────────────────────────
# camelCase / snake_case splitting
# ──────────────────────────────────────────────


class TestFTSTokenization:
    """FTS5 index splits camelCase and snake_case for partial word matching."""

    def test_camel_prefix_matches_class(self, populated_store: GraphStore) -> None:
        """'auth' should find 'AuthService' via camelCase split."""
        results = populated_store.search_nodes("auth")
        names = [n.name for n in results]
        assert "AuthService" in names

    def test_camel_suffix_matches_class(self, populated_store: GraphStore) -> None:
        """'service' should find 'AuthService' and 'PaymentGateway' — wait, 'service' is in Auth."""
        results = populated_store.search_nodes("service")
        names = [n.name for n in results]
        assert "AuthService" in names

    def test_snake_word_matches_method(self, populated_store: GraphStore) -> None:
        """'create' should find 'create_user' via snake_case split."""
        results = populated_store.search_nodes("create")
        names = [n.name for n in results]
        assert "create_user" in names

    def test_camel_word_matches_method(self, populated_store: GraphStore) -> None:
        """'validate' should find 'validateEmail' via camelCase split."""
        results = populated_store.search_nodes("validate")
        names = [n.name for n in results]
        assert "validateEmail" in names

    def test_gateway_word_found(self, populated_store: GraphStore) -> None:
        """'gateway' should find 'PaymentGateway'."""
        results = populated_store.search_nodes("gateway")
        names = [n.name for n in results]
        assert "PaymentGateway" in names


# ──────────────────────────────────────────────
# Docstring / signature search
# ──────────────────────────────────────────────


class TestFTSDocstringSearch:
    """FTS5 searches across signature and docstring content."""

    def test_finds_by_docstring_word(self, populated_store: GraphStore) -> None:
        """'authentication' in docstring should match AuthService."""
        results = populated_store.search_nodes("authentication")
        names = [n.name for n in results]
        assert "AuthService" in names

    def test_finds_by_docstring_concept(self, populated_store: GraphStore) -> None:
        """'credit' appears in PaymentGateway's docstring."""
        results = populated_store.search_nodes("credit")
        names = [n.name for n in results]
        assert "PaymentGateway" in names or "charge" in names

    def test_finds_by_signature_word(self, populated_store: GraphStore) -> None:
        """'amount' appears in charge's signature."""
        results = populated_store.search_nodes("amount")
        names = [n.name for n in results]
        assert "charge" in names


# ──────────────────────────────────────────────
# Multi-word queries (AND logic)
# ──────────────────────────────────────────────


class TestFTSMultiWord:
    """Multi-word queries require ALL words to match (AND)."""

    def test_two_words_both_required(self, populated_store: GraphStore) -> None:
        """'payment gateway' matches PaymentGateway but not AuthService."""
        results = populated_store.search_nodes("payment gateway")
        names = [n.name for n in results]
        assert "PaymentGateway" in names
        assert "AuthService" not in names

    def test_two_words_no_match(self, populated_store: GraphStore) -> None:
        """'auth gateway' matches nothing (auth is auth.py, gateway is payment)."""
        results = populated_store.search_nodes("auth gateway")
        # auth and gateway don't co-occur in the same node
        assert len(results) == 0

    def test_prefix_multi_word(self, populated_store: GraphStore) -> None:
        """'auth serv' finds AuthService via prefix matching."""
        results = populated_store.search_nodes("auth serv")
        names = [n.name for n in results]
        assert "AuthService" in names


# ──────────────────────────────────────────────
# kind filter
# ──────────────────────────────────────────────


class TestFTSKindFilter:
    """--kind filter works together with FTS5."""

    def test_kind_class_filters_methods(self, populated_store: GraphStore) -> None:
        results = populated_store.search_nodes("auth", kind="Class")
        assert all(n.kind == "Class" for n in results)

    def test_kind_method_excludes_classes(self, populated_store: GraphStore) -> None:
        results = populated_store.search_nodes("auth", kind="Method")
        assert all(n.kind == "Method" for n in results)
        names = [n.name for n in results]
        assert "AuthService" not in names


# ──────────────────────────────────────────────
# FTS stays in sync with store_file updates
# ──────────────────────────────────────────────


class TestFTSSync:
    """FTS index stays consistent when files are re-indexed or removed."""

    def test_reindex_updates_fts(self, store: GraphStore) -> None:
        """Re-indexing a file with new content updates FTS results."""
        node = NodeInfo(
            kind=NodeKind.CLASS,
            name="OldName",
            qualified_name="src/x.py::OldName",
            file_path="src/x.py",
            docstring="old docstring content",
        )
        store.store_file("src/x.py", [node], [], "h1")
        assert store.search_nodes("old")

        node2 = NodeInfo(
            kind=NodeKind.CLASS,
            name="NewName",
            qualified_name="src/x.py::NewName",
            file_path="src/x.py",
            docstring="new docstring content",
        )
        store.store_file("src/x.py", [node2], [], "h2")

        assert store.search_nodes("new")
        assert not store.search_nodes("old")  # old entry must be gone

    def test_remove_file_cleans_fts(self, store: GraphStore) -> None:
        """Removing a file removes its nodes from FTS."""
        node = NodeInfo(
            kind=NodeKind.CLASS,
            name="TempService",
            qualified_name="src/temp.py::TempService",
            file_path="src/temp.py",
        )
        store.store_file("src/temp.py", [node], [], "h1")
        assert store.search_nodes("temp")

        store.remove_file("src/temp.py")
        assert not store.search_nodes("temp")
