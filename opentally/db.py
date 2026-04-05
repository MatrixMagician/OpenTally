"""
opentally/db.py – SQLCipher-backed storage for elections and voters.

PRAGMA key note: Parameterised binding for PRAGMA key is unreliable across
sqlcipher3 builds (some builds silently ignore the bound value).  We therefore
use a literal PRAGMA string with the passphrase embedded, escaping any embedded
single-quotes by doubling them.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    import sqlcipher3 as _sqlcipher
except ImportError:
    import pysqlcipher3.dbapi2 as _sqlcipher  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WrongPassphraseError(Exception):
    """Raised when the supplied passphrase cannot decrypt the database."""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def open_db(path: str, passphrase: str) -> _sqlcipher.Connection:
    """Open (or create) an encrypted SQLite database at *path*.

    Returns an open connection with ``row_factory`` set to ``sqlite3.Row``.
    Raises ``WrongPassphraseError`` if *passphrase* is incorrect.
    """
    conn = _sqlcipher.connect(path)

    # Embed the passphrase as a literal string, escaping embedded single-quotes
    # by doubling them (SQL standard).  Parameterised binding is intentionally
    # avoided – see module docstring.
    safe_passphrase = passphrase.replace("'", "''")
    conn.execute("PRAGMA key = '{}'".format(safe_passphrase))

    # A failed passphrase surfaces as a DatabaseError on the first real query.
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except _sqlcipher.DatabaseError as exc:
        conn.close()
        raise WrongPassphraseError("Incorrect passphrase or corrupted database") from exc

    # sqlite3.Row cannot be used with sqlcipher3 cursors (different C types).
    # We use a simple dict row_factory instead, which is equally convenient.
    def _dict_row(cursor, row):
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

    conn.row_factory = _dict_row
    return conn


def create_tables(conn: _sqlcipher.Connection) -> None:
    """Create the elections and voters tables if they do not already exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elections (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL,
            start_time       INTEGER NOT NULL DEFAULT 0,
            end_time         INTEGER NOT NULL DEFAULT 0,
            contract_address TEXT,
            created_at       TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voters (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id  INTEGER NOT NULL REFERENCES elections(id),
            name         TEXT    NOT NULL,
            eth_address  TEXT    NOT NULL,
            registered_at TEXT   NOT NULL
        )
    """)
    conn.commit()


def close_db(conn: _sqlcipher.Connection) -> None:
    """Commit any pending changes and close the connection."""
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Election CRUD
# ---------------------------------------------------------------------------

def insert_election(
    conn: _sqlcipher.Connection,
    name: str,
    start_time: int = 0,
    end_time: int = 0,
    contract_address: str | None = None,
) -> int:
    """Insert a new election row and return its rowid."""
    created_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO elections (name, start_time, end_time, contract_address, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, start_time, end_time, contract_address, created_at),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_elections(conn: _sqlcipher.Connection) -> list[dict]:
    """Return all elections as a list of dicts."""
    rows = conn.execute("SELECT * FROM elections ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def update_election_contract(
    conn: _sqlcipher.Connection,
    election_id: int,
    contract_address: str,
) -> None:
    """Set the on-chain contract address for *election_id*."""
    conn.execute(
        "UPDATE elections SET contract_address = ? WHERE id = ?",
        (contract_address, election_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Voter CRUD
# ---------------------------------------------------------------------------

def insert_voter(
    conn: _sqlcipher.Connection,
    election_id: int,
    name: str,
    eth_address: str,
) -> int:
    """Insert a voter record and return its rowid."""
    registered_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO voters (election_id, name, eth_address, registered_at) "
        "VALUES (?, ?, ?, ?)",
        (election_id, name, eth_address, registered_at),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_voters(conn: _sqlcipher.Connection, election_id: int) -> list[dict]:
    """Return all voters for *election_id* as a list of dicts."""
    rows = conn.execute(
        "SELECT * FROM voters WHERE election_id = ? ORDER BY id",
        (election_id,),
    ).fetchall()
    return [dict(row) for row in rows]
