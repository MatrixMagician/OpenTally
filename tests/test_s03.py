#!/usr/bin/env python3
"""End-to-end integration test: voting flow chain functions (S03).

Exercises the cast_vote / get_results / double-vote-revert boundary that
VotingScreen depends on — without running Textual itself.

Usage:
    python3 tests/test_s03.py

Exit 0 on success, non-zero on any assertion failure.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path so opentally.* are importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opentally import chain  # noqa: E402


# ---------------------------------------------------------------------------
# Anvil helpers (same pattern as tests/test_s02.py)
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


def _step(msg: str) -> None:
    print(f"  [step] {msg}")


# ---------------------------------------------------------------------------
# Main test body
# ---------------------------------------------------------------------------


def run_tests() -> None:
    anvil_proc = None

    try:
        # ---- Step 1: Spawn Anvil ----------------------------------------
        _step("Starting Anvil on port 8545 ...")
        anvil_proc = _start_anvil()

        _step("Waiting for Anvil to be ready ...")
        w3 = _wait_connected(timeout=10.0)
        _step(f"Connected. Chain ID: {w3.eth.chain_id}")

        accounts = w3.eth.accounts
        sender = accounts[0]

        # ---- Step 2: Compile + deploy contract --------------------------
        _step("Compiling and deploying Voting contract ...")
        contract = chain.deploy(w3, sender)
        _step(f"Contract deployed at {contract.address}")

        # ---- Step 3: Create election ------------------------------------
        _step("Creating election 'Test Election' ...")
        chain.create_election(contract, sender, "Test Election", 0, 0)
        _step("  -> Election created ✓")

        # ---- Step 4: Add candidates Alice and Bob -----------------------
        _step("Adding candidates Alice and Bob ...")
        chain.add_candidate(contract, sender, "Alice")
        chain.add_candidate(contract, sender, "Bob")
        _step("  -> 2 candidates added ✓")

        # ---- Step 5: Register two voters --------------------------------
        voter1, voter2 = accounts[1], accounts[2]
        _step(f"Registering voters {voter1[:10]}... and {voter2[:10]}... ...")
        chain.register_voter(contract, sender, voter1)
        chain.register_voter(contract, sender, voter2)
        _step("  -> Both voters registered ✓")

        # ---- Step 6: Cast votes -----------------------------------------
        _step("voter1 votes for Alice (index 0) ...")
        chain.cast_vote(contract, voter1, 0)
        _step("  -> voter1 vote cast ✓")

        _step("voter2 votes for Bob (index 1) ...")
        chain.cast_vote(contract, voter2, 1)
        _step("  -> voter2 vote cast ✓")

        # ---- Step 7: Verify results [1, 1] ------------------------------
        _step("Fetching results ...")
        names, counts = chain.get_results(contract)
        _step(f"  -> names={names}, counts={counts}")
        assert counts == [1, 1], f"Expected [1, 1], got {counts}"
        assert names == ["Alice", "Bob"], f"Expected ['Alice', 'Bob'], got {names}"
        _step("  -> Results correct: Alice=1, Bob=1 ✓")

        # ---- Step 8: Double-vote revert ---------------------------------
        _step("Attempting double-vote (voter1 votes again) ...")
        from web3.exceptions import ContractLogicError  # noqa: E402

        double_vote_caught = False
        try:
            chain.cast_vote(contract, voter1, 0)
        except ContractLogicError as e:
            assert "Already voted" in str(e), (
                f"Expected 'Already voted' in error, got: {e}"
            )
            double_vote_caught = True
            _step(f"  -> ContractLogicError raised as expected: {e} ✓")

        assert double_vote_caught, "Double-vote did NOT raise ContractLogicError!"

        print()
        print("S03 INTEGRATION PASSED")
        sys.exit(0)

    except Exception as exc:
        print(f"\nTEST FAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    finally:
        if anvil_proc is not None:
            _step("Terminating Anvil ...")
            anvil_proc.terminate()
            try:
                anvil_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                anvil_proc.kill()


if __name__ == "__main__":
    run_tests()
