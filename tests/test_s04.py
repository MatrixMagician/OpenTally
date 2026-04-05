#!/usr/bin/env python3
"""End-to-end integration test: results screen chain functions + turnout (S04).

Exercises chain.get_results, winner determination, and turnout calculation
against a live Anvil chain, using a real in-memory SQLCipher DB for the voter
denominator — matching the ResultsScreen code path in opentally/app.py.

Usage:
    python3 tests/test_s04.py

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


# ---------------------------------------------------------------------------
# Anvil helpers (same pattern as tests/test_s03.py)
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


def _start_anvil() -> subprocess.Popen:
    anvil_bin = _find_anvil()
    return subprocess.Popen(
        [anvil_bin, "--port", "8545", "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


def _step(n: int, msg: str) -> None:
    print(f"  [step{n}] {msg}")


# ---------------------------------------------------------------------------
# Main test body
# ---------------------------------------------------------------------------


def run_tests() -> None:
    anvil_proc = None
    conn = None

    try:
        # ---- Step 1: Spawn Anvil ----------------------------------------
        _step(1, "Starting Anvil on port 8545 ...")
        anvil_proc = _start_anvil()

        _step(1, "Waiting for Anvil to be ready ...")
        w3 = _wait_connected(timeout=10.0)
        _step(1, f"Connected. Chain ID: {w3.eth.chain_id}")

        accounts = w3.eth.accounts

        # ---- Step 2: Open in-memory SQLCipher DB ------------------------
        _step(2, "Initialising temporary SQLCipher DB ...")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name
        conn = db.open_db(db_path, "testpassphrase")
        db.create_tables(conn)
        election_id = db.insert_election(conn, "Test Election", 0, 0)
        _step(2, f"  -> DB opened, election_id={election_id} ✓")

        # ---- Step 3: Deploy contract ------------------------------------
        _step(3, "Compiling and deploying Voting contract ...")
        contract = chain.deploy(w3, accounts[0])
        _step(3, f"Contract deployed at {contract.address}")

        # ---- Step 4: Create election on-chain ---------------------------
        _step(4, "Creating election 'Test Election' on chain ...")
        chain.create_election(contract, accounts[0], "Test Election", 0, 0)
        _step(4, "  -> Election created ✓")

        # ---- Step 5: Add candidates Alice, Bob, Carol -------------------
        _step(5, "Adding candidates Alice, Bob, Carol ...")
        chain.add_candidate(contract, accounts[0], "Alice")
        chain.add_candidate(contract, accounts[0], "Bob")
        chain.add_candidate(contract, accounts[0], "Carol")
        _step(5, "  -> 3 candidates added ✓")

        # ---- Step 6: Register 4 voters (chain + DB) ---------------------
        _step(6, "Registering 4 voters on chain and in DB ...")
        voters = accounts[1:5]  # accounts[1], [2], [3], [4]
        for i, addr in enumerate(voters):
            chain.register_voter(contract, accounts[0], addr)
            db.insert_voter(conn, election_id, f"Voter{i+1}", addr)
        registered = db.get_voters(conn, election_id)
        assert len(registered) == 4, f"Expected 4 voters in DB, got {len(registered)}"
        _step(6, f"  -> 4 voters registered (DB count={len(registered)}) ✓")

        # ---- Step 7: Cast votes (3 of 4 vote, leaving accounts[4] idle) -
        _step(7, "Casting votes: accounts[1]→Alice, accounts[2]→Alice, accounts[3]→Bob ...")
        chain.cast_vote(contract, accounts[1], 0)  # Alice
        chain.cast_vote(contract, accounts[2], 0)  # Alice
        chain.cast_vote(contract, accounts[3], 1)  # Bob
        # accounts[4] deliberately does NOT vote → turnout < 100%
        _step(7, "  -> 3 votes cast ✓")

        # ---- Step 8: Verify results -------------------------------------
        _step(8, "Fetching results from chain ...")
        names, counts = chain.get_results(contract)
        _step(8, f"  -> names={names}, counts={counts}")
        assert names == ["Alice", "Bob", "Carol"], (
            f"Expected ['Alice','Bob','Carol'], got {names}"
        )
        assert counts == [2, 1, 0], f"Expected [2,1,0], got {counts}"
        _step(8, "  -> Results correct: Alice=2, Bob=1, Carol=0 ✓")

        # ---- Step 9: Compute and assert turnout -------------------------
        _step(9, "Computing turnout ...")
        total_voters = len(db.get_voters(conn, election_id))
        votes_cast = sum(counts)
        turnout = votes_cast / total_voters * 100
        _step(9, f"  -> votes_cast={votes_cast}, total_voters={total_voters}, turnout={turnout}%")
        assert turnout == 75.0, f"Expected turnout 75.0%, got {turnout}%"
        _step(9, "  -> Turnout correct: 75.0% ✓")

        # ---- Step 10: Determine winner -----------------------------------
        _step(10, "Determining winner ...")
        max_count = max(counts)
        winners = [names[i] for i, c in enumerate(counts) if c == max_count]
        is_tie = len(winners) > 1
        winner = winners[0] if not is_tie else None
        _step(10, f"  -> winner={winner}, is_tie={is_tie}")
        assert winner == "Alice", f"Expected winner 'Alice', got {winner}"
        assert not is_tie, "Unexpected tie in results"
        _step(10, "  -> Winner correct: Alice ✓")

        print()
        print("S04 INTEGRATION PASSED")
        return True

    except Exception as exc:
        print(f"\nTEST FAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False

    finally:
        if conn is not None:
            try:
                db.close_db(conn)
            except Exception:
                pass
        if anvil_proc is not None:
            _step(12, "Terminating Anvil ...")
            anvil_proc.terminate()
            try:
                anvil_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                anvil_proc.kill()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
