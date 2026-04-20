"""Git clean/smudge filters for ``.codeindex/index.db``.

These entry points are installed by ``codeindex init`` as git filter drivers
so that the binary SQLite database is stored in git as a portable SQL text
dump instead of a raw binary blob.

How it works
------------
- **clean** (``codeindex-clean``): run by git on ``git add`` — converts the
  SQLite binary to SQL text that git stores internally.
- **smudge** (``codeindex-smudge``): run by git on ``git checkout`` — converts
  the SQL text back to a SQLite binary in the working tree.
- **textconv** (also ``codeindex-clean``): when a filename is supplied as
  ``argv[1]``, the clean command reads from that file instead of stdin, making
  it usable as a ``diff.codeindex.textconv`` driver.

Usage (configured automatically by ``codeindex init``)::

    # .gitattributes
    .codeindex/index.db filter=codeindex diff=codeindex merge=ours

    # .git/config (local)
    [filter "codeindex"]
        clean    = codeindex-clean
        smudge   = codeindex-smudge
        required = false
    [diff "codeindex"]
        textconv = codeindex-clean
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import structlog

log = structlog.get_logger()

# Virtual tables (FTS5, sqlite-vec) that require external extensions to dump.
# They are excluded from the SQL dump and rebuilt by ``codeindex index .``
# via the post-checkout / post-merge hooks installed by ``codeindex init``.
_VIRTUAL_TABLE_PREFIXES = ("nodes_fts", "node_embeddings")


# ──────────────────────────────────────────────
# Core helpers (testable without stdin/stdout)
# ──────────────────────────────────────────────


def _is_virtual(sql: str) -> bool:
    """Return True if a CREATE TABLE statement defines a virtual table."""
    return sql.strip().upper().startswith("CREATE VIRTUAL")


def dump_db(db_path: str | Path) -> str:
    """Dump the regular (non-virtual) tables of a SQLite database to SQL text.

    Virtual tables such as ``nodes_fts`` (FTS5) and ``node_embeddings``
    (sqlite-vec) are intentionally excluded because their extension modules may
    not be available in every environment.  They are recreated automatically
    when :class:`~codeindex.graph_store.GraphStore` opens the restored database
    and the post-checkout/post-merge hooks re-run the indexer.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A SQL text dump (``BEGIN TRANSACTION … COMMIT;``) containing only
        regular tables and their data.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.row_factory = None

        # Collect all user-defined table entries (excludes SQLite internals)
        schema = cur.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()

        # Identify virtual table names so we can also skip their shadow tables.
        # Shadow tables follow the naming pattern: "{virtual_name}_{suffix}".
        virtual_names: set[str] = {name for name, sql in schema if _is_virtual(sql)}

        lines: list[str] = ["BEGIN TRANSACTION;"]
        for table_name, create_sql in schema:
            # Skip virtual tables (FTS5, vec0, …)
            if _is_virtual(create_sql):
                continue
            # Skip shadow tables created internally by virtual-table extensions
            if any(table_name.startswith(vname + "_") for vname in virtual_names):
                continue

            lines.append(f"{create_sql};")

            # Dump rows with hand-rolled escaping (no external dependency).
            # table_name comes from sqlite_master of our own DB — not user input.
            rows = cur.execute(f'SELECT * FROM "{table_name}"').fetchall()  # nosec B608
            for row in rows:
                placeholders = ", ".join(
                    "NULL"
                    if v is None
                    else str(v)
                    if isinstance(v, (int, float))
                    else "'" + str(v).replace("'", "''") + "'"
                    for v in row
                )
                lines.append(f'INSERT INTO "{table_name}" VALUES({placeholders});')  # nosec B608

        lines.append("COMMIT;")
        return "\n".join(lines) + "\n"
    finally:
        conn.close()


def restore_db(sql: str, db_path: str | Path) -> None:
    """Reconstruct a SQLite database from a SQL dump string.

    Creates any missing parent directories automatically.

    Args:
        sql: SQL dump produced by :func:`dump_db` or ``sqlite3 .dump``.
        db_path: Destination path for the SQLite database file.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(sql)
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Entry points
# ──────────────────────────────────────────────


def cmd_clean() -> None:
    """Git clean filter / textconv: SQLite → SQL dump on stdout.

    Modes:

    * **textconv** — when ``sys.argv[1]`` is a filename, read from that file.
    * **filter clean** — when no argument is given, read binary SQLite from
      ``sys.stdin.buffer`` (git pipes the file content).

    The output SQL is written to stdout so git can store it as a text object.
    """
    if len(sys.argv) > 1:
        # textconv mode: git passes the filename as an argument
        sql = dump_db(sys.argv[1])
    else:
        # filter clean mode: git pipes the binary file content via stdin
        data = sys.stdin.buffer.read()
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        try:
            os.write(fd, data)
            os.close(fd)
            sql = dump_db(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    sys.stdout.write(sql)


def cmd_smudge() -> None:
    """Git smudge filter: SQL dump (stdin) → SQLite binary (stdout).

    Git pipes the stored SQL text through stdin; this command reconstructs the
    SQLite binary and writes it to ``sys.stdout.buffer`` so git places the
    working-tree file correctly.
    """
    sql = sys.stdin.read()
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        restore_db(sql, tmp_path)
        with open(tmp_path, "rb") as fh:
            sys.stdout.buffer.write(fh.read())
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
