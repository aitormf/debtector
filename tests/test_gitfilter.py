"""Tests for codeindex.gitfilter — clean/smudge filter utilities."""

from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

from codeindex.gitfilter import dump_db, restore_db

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _make_sqlite(path: Path) -> None:
    """Create a minimal SQLite DB with one table and a few rows."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.executemany("INSERT INTO items (name) VALUES (?)", [("alpha",), ("beta",), ("gamma",)])
    conn.commit()
    conn.close()


def _read_names(path: Path) -> list[str]:
    """Return all names from the items table of *path*."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT name FROM items ORDER BY name").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────
# dump_db
# ──────────────────────────────────────────────


class TestDumpDb:
    """Tests for dump_db()."""

    def test_returns_string(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_sqlite(db)
        result = dump_db(db)
        assert isinstance(result, str)

    def test_contains_create_table(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_sqlite(db)
        sql = dump_db(db)
        assert "CREATE TABLE items" in sql

    def test_contains_row_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_sqlite(db)
        sql = dump_db(db)
        assert "alpha" in sql
        assert "beta" in sql
        assert "gamma" in sql

    def test_accepts_path_or_str(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _make_sqlite(db)
        assert dump_db(str(db)) == dump_db(db)


# ──────────────────────────────────────────────
# restore_db
# ──────────────────────────────────────────────


class TestRestoreDb:
    """Tests for restore_db()."""

    def test_creates_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        dst = tmp_path / "dst.db"
        _make_sqlite(src)
        restore_db(dump_db(src), dst)
        assert dst.exists()

    def test_restored_db_is_readable_sqlite(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        dst = tmp_path / "dst.db"
        _make_sqlite(src)
        restore_db(dump_db(src), dst)
        # Should open as SQLite without error
        conn = sqlite3.connect(str(dst))
        conn.execute("SELECT 1").fetchone()
        conn.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        dst = tmp_path / "sub" / "deep" / "dst.db"
        _make_sqlite(src)
        restore_db(dump_db(src), dst)
        assert dst.exists()

    def test_accepts_path_or_str(self, tmp_path: Path) -> None:
        src = tmp_path / "src.db"
        dst1 = tmp_path / "dst1.db"
        dst2 = tmp_path / "dst2.db"
        _make_sqlite(src)
        restore_db(dump_db(src), str(dst1))
        restore_db(dump_db(src), dst2)
        assert dst1.exists() and dst2.exists()


# ──────────────────────────────────────────────
# Roundtrip
# ──────────────────────────────────────────────


class TestRoundtrip:
    """Full clean → smudge roundtrip preserves all data."""

    def test_data_preserved_after_roundtrip(self, tmp_path: Path) -> None:
        src = tmp_path / "original.db"
        restored = tmp_path / "restored.db"
        _make_sqlite(src)

        sql = dump_db(src)
        restore_db(sql, restored)

        assert _read_names(src) == _read_names(restored)

    def test_roundtrip_with_graphstore_db(self, tmp_db) -> None:
        """A real GraphStore DB survives a clean→smudge roundtrip intact."""
        from codeindex.models import NodeInfo, NodeKind

        nodes = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="app.py",
                qualified_name="src/app.py",
                file_path="src/app.py",
                line_start=1,
                line_end=10,
                language="python",
            )
        ]
        tmp_db.store_file("src/app.py", nodes, [], "deadbeef")
        src_path = tmp_db.db_path
        restored_path = src_path.parent / "restored.db"

        restore_db(dump_db(src_path), restored_path)

        from codeindex.graph_store import GraphStore

        with GraphStore(restored_path) as store:
            result = store.get_nodes_by_file("src/app.py")
        assert len(result) == 1
        assert result[0].name == "app.py"


# ──────────────────────────────────────────────
# cmd_clean (entry point)
# ──────────────────────────────────────────────


class TestCmdClean:
    """Tests for cmd_clean() entry point."""

    def test_clean_from_file_argument(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """When a filename is passed as argv[1], clean reads from that file."""
        from codeindex.gitfilter import cmd_clean

        db = tmp_path / "test.db"
        _make_sqlite(db)
        monkeypatch.setattr(sys, "argv", ["codeindex-clean", str(db)])
        cmd_clean()
        out = capsys.readouterr().out
        assert "CREATE TABLE items" in out
        assert "alpha" in out

    def test_clean_from_stdin(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """When no args, clean reads SQLite binary from stdin."""
        from codeindex.gitfilter import cmd_clean

        db = tmp_path / "test.db"
        _make_sqlite(db)
        monkeypatch.setattr(sys, "argv", ["codeindex-clean"])
        monkeypatch.setattr(sys, "stdin", io.BytesIO(db.read_bytes()))
        # stdin needs a .buffer attribute for binary reads
        stdin_mock = type("FakeStdin", (), {"buffer": io.BytesIO(db.read_bytes())})()
        monkeypatch.setattr(sys, "stdin", stdin_mock)
        cmd_clean()
        out = capsys.readouterr().out
        assert "CREATE TABLE items" in out


# ──────────────────────────────────────────────
# cmd_smudge (entry point)
# ──────────────────────────────────────────────


class TestCmdSmudge:
    """Tests for cmd_smudge() entry point."""

    def test_smudge_writes_sqlite_to_stdout(self, tmp_path: Path, monkeypatch) -> None:
        """cmd_smudge writes a valid SQLite binary to stdout."""
        from codeindex.gitfilter import cmd_smudge

        db = tmp_path / "test.db"
        _make_sqlite(db)
        sql = dump_db(db)

        monkeypatch.setattr(sys, "argv", ["codeindex-smudge"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(sql))

        stdout_buf = io.BytesIO()
        stdout_mock = type("FakeStdout", (), {"buffer": stdout_buf})()
        monkeypatch.setattr(sys, "stdout", stdout_mock)

        cmd_smudge()

        binary = stdout_buf.getvalue()
        # SQLite magic header: first 16 bytes are "SQLite format 3\x00"
        assert binary[:6] == b"SQLite"
