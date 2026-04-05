#!/usr/bin/env python3
"""
Standalone test script for opentally/db.py.

Run:  python3 tests/test_db.py
Exit: 0 on success, 1 on failure.
"""

import sys
import tempfile
import os

# Ensure the repo root is on the path so opentally can be imported.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from opentally.db import (
    WrongPassphraseError,
    close_db,
    create_tables,
    get_elections,
    get_voters,
    insert_election,
    insert_voter,
    open_db,
    update_election_contract,
)

PASSPHRASE = "testpass"
WRONG_PASSPHRASE = "wrongpass"


def run_tests() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # ------------------------------------------------------------------ #
        # 1. Create DB, tables, insert data                                   #
        # ------------------------------------------------------------------ #
        conn = open_db(db_path, PASSPHRASE)
        create_tables(conn)

        eid = insert_election(conn, "General Election 2025", start_time=1_000_000, end_time=2_000_000)
        assert isinstance(eid, int) and eid > 0, f"Expected positive int election id, got {eid!r}"

        vid1 = insert_voter(conn, eid, "Alice", "0xABCDEF1234567890")
        vid2 = insert_voter(conn, eid, "Bob",   "0x0987654321FEDCBA")
        assert vid1 != vid2, "Voter IDs should be distinct"

        # Round-trip election
        elections = get_elections(conn)
        assert len(elections) == 1, f"Expected 1 election, got {len(elections)}"
        assert elections[0]["name"] == "General Election 2025"
        assert elections[0]["start_time"] == 1_000_000
        assert elections[0]["contract_address"] is None

        # Round-trip voters
        voters = get_voters(conn, eid)
        assert len(voters) == 2, f"Expected 2 voters, got {len(voters)}"
        names = {v["name"] for v in voters}
        assert names == {"Alice", "Bob"}, f"Unexpected voter names: {names}"

        # Update contract address
        update_election_contract(conn, eid, "0xDeAdBeEf")
        elections2 = get_elections(conn)
        assert elections2[0]["contract_address"] == "0xDeAdBeEf"

        close_db(conn)

        # ------------------------------------------------------------------ #
        # 2. Reopen with wrong passphrase → WrongPassphraseError              #
        # ------------------------------------------------------------------ #
        raised = False
        try:
            bad_conn = open_db(db_path, WRONG_PASSPHRASE)
            bad_conn.close()
        except WrongPassphraseError:
            raised = True
        assert raised, "Expected WrongPassphraseError with wrong passphrase"

        # ------------------------------------------------------------------ #
        # 3. Reopen with correct passphrase → rows still intact               #
        # ------------------------------------------------------------------ #
        conn2 = open_db(db_path, PASSPHRASE)
        elections3 = get_elections(conn2)
        assert len(elections3) == 1, "Persisted elections not found after reopen"
        assert elections3[0]["name"] == "General Election 2025"

        voters3 = get_voters(conn2, eid)
        assert len(voters3) == 2, "Persisted voters not found after reopen"
        close_db(conn2)

    finally:
        os.unlink(db_path)

    print("DB TESTS PASSED")


if __name__ == "__main__":
    try:
        run_tests()
        sys.exit(0)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
