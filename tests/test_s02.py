#!/usr/bin/env python3
"""End-to-end integration test: SQLCipher DB + chain.py (S02).

Exercises the boundary contract between db.py, chain.py, and the operator
action patterns that app.py uses — without running Textual itself.

Usage:
    python3 tests/test_s02.py

Exit 0 on success, non-zero on any assertion failure.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure repo root is on sys.path so opentally.* are importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentally import chain, db  # noqa: E402
from opentally.db import WrongPassphraseError  # noqa: E402


# ---------------------------------------------------------------------------
# Anvil helpers (reused pattern from tests/test_contract.py)
# ---------------------------------------------------------------------------


def _find_anvil() -> str:
    candidate = shutil.which("anvil")
    if candidate:
        return candidate
    fallback = Path.home() / ".foundry" / "bin" / "anvil"
    if fallback.exists():
        return str(fallback)
    raise RuntimeError(
        "anvil not found on PATH and ~/.foundry/bin/anvil does not exist. "
        "Install Foundry: https://book.getfoundry.sh/getting-started/installation"
    )


def _start_anvil(log_path: str) -> subprocess.Popen:
    anvil_bin = _find_anvil()
    log_fh = open(log_path, "w")
    return subprocess.Popen(
        [anvil_bin, "--port", "8545", "--silent"],
        stdout=log_fh,
        stderr=log_fh,
    )


def _wait_connected(rpc_url: str = "http://127.0.0.1:8545", timeout: float = 10.0):
    deadline = time.time() + timeout
    w3 = chain.connect(rpc_url)
    while time.time() < deadline:
        if w3.is_connected():
            return w3
        time.sleep(0.2)
        w3 = chain.connect(rpc_url)
    raise TimeoutError(f"Could not connect to {rpc_url} within {timeout}s")


def _step(msg: str) -> None:
    print(f"  [step] {msg}")


# ---------------------------------------------------------------------------
# Main test body
# ---------------------------------------------------------------------------


def run_tests() -> None:
    tmp_dir = tempfile.mkdtemp(prefix="opentally_s02_test_")
    anvil_log = str(Path(tmp_dir) / "anvil.log")
    db_path = str(Path(tmp_dir) / "test.db")
    passphrase = "integration-test"
    conn = None
    anvil_proc = None

    try:
        # ---- Start Anvil -----------------------------------------------
        _step("Starting Anvil on port 8545 ...")
        anvil_proc = _start_anvil(anvil_log)

        _step("Waiting for Anvil to be ready ...")
        w3 = _wait_connected(timeout=10.0)
        _step(f"Connected. Chain ID: {w3.eth.chain_id}")

        accounts = w3.eth.accounts
        sender = accounts[0]

        # ---- Open DB and create tables ---------------------------------
        _step("Opening encrypted DB ...")
        conn = db.open_db(db_path, passphrase)
        db.create_tables(conn)
        _step("DB opened and tables created.")

        # ---- Wrong passphrase check ------------------------------------
        _step("Testing wrong-passphrase detection ...")
        db.close_db(conn)
        conn = None
        caught = False
        try:
            bad_conn = db.open_db(db_path, "wrong")
            bad_conn.close()
        except WrongPassphraseError:
            caught = True
        assert caught, "WrongPassphraseError was NOT raised for a bad passphrase!"
        _step("  -> WrongPassphraseError raised correctly ✓")

        # Reopen with correct passphrase
        conn = db.open_db(db_path, passphrase)
        _step("  -> Correct passphrase accepted ✓")

        # ---- Compile + deploy contract ----------------------------------
        _step("Compiling and deploying Voting contract ...")
        contract = chain.deploy(w3, sender)
        _step(f"Contract deployed at {contract.address}")

        # ---- Create election on-chain and in DB ------------------------
        _step("Creating election 'Test Election' ...")
        chain.create_election(contract, sender, "Test Election", 0, 0)
        election_id = db.insert_election(conn, "Test Election")
        db.update_election_contract(conn, election_id, contract.address)
        _step(f"  -> Election id={election_id}, address={contract.address}")

        # ---- Add candidates --------------------------------------------
        _step("Adding candidates Alice and Bob ...")
        chain.add_candidate(contract, sender, "Alice")
        chain.add_candidate(contract, sender, "Bob")

        # ---- Register 2 voters -----------------------------------------
        voter1, voter2 = accounts[1], accounts[2]
        _step(f"Registering voters {voter1} and {voter2} ...")
        db.insert_voter(conn, election_id, "Voter One", voter1)
        chain.register_voter(contract, sender, voter1)
        db.insert_voter(conn, election_id, "Voter Two", voter2)
        chain.register_voter(contract, sender, voter2)

        # ---- Assert DB state -------------------------------------------
        _step("Asserting DB state ...")
        voters = db.get_voters(conn, election_id)
        assert len(voters) == 2, f"Expected 2 voters, got {len(voters)}"
        _step(f"  -> get_voters returned {len(voters)} rows ✓")

        elections = db.get_elections(conn)
        assert elections[0]["contract_address"] == contract.address, (
            f"Expected {contract.address}, got {elections[0]['contract_address']}"
        )
        _step("  -> contract_address stored correctly ✓")

        # ---- Verify DB file is encrypted --------------------------------
        _step("Verifying DB file is not plaintext SQLite ...")
        with open(db_path, "rb") as fh:
            header = fh.read(16)
        assert not header.startswith(b"SQLite format 3"), (
            "DB header matches plaintext SQLite — encryption is NOT active!"
        )
        _step(f"  -> Header bytes: {header.hex()} (not plaintext SQLite) ✓")

        print()
        print("S02 INTEGRATION PASSED")

    except Exception as exc:
        print(f"\nTEST FAILED: {exc}", file=sys.stderr)
        if anvil_proc is not None:
            try:
                with open(anvil_log) as f:
                    print("--- Anvil log ---", file=sys.stderr)
                    print(f.read(), file=sys.stderr)
            except OSError:
                pass
        sys.exit(1)

    finally:
        if conn is not None:
            try:
                db.close_db(conn)
            except Exception:
                pass
        if anvil_proc is not None:
            _step("Terminating Anvil ...")
            anvil_proc.terminate()
            try:
                anvil_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                anvil_proc.kill()
        # Clean up temp files
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    run_tests()
