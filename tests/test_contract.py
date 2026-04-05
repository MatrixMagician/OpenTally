#!/usr/bin/env python3
"""Self-contained end-to-end test for the Voting smart contract.

Usage:
    python3 tests/test_contract.py

Exit 0 on success, non-zero on any assertion failure.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure repo root is on sys.path so opentally.chain is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import opentally.chain as chain  # noqa: E402
from web3.exceptions import ContractLogicError  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_anvil() -> str:
    """Return the path to the anvil binary, or raise RuntimeError."""
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
    """Start anvil on port 8545, redirect output to log_path."""
    anvil_bin = _find_anvil()
    log_fh = open(log_path, "w")
    proc = subprocess.Popen(
        [anvil_bin, "--port", "8545", "--silent"],
        stdout=log_fh,
        stderr=log_fh,
    )
    return proc


def _wait_connected(rpc_url: str = "http://127.0.0.1:8545", timeout: float = 10.0) -> "Web3":
    """Poll until web3 connects or timeout; return Web3 instance."""
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
    tmp_dir = tempfile.mkdtemp(prefix="opentally_test_")
    anvil_log = str(Path(tmp_dir) / "anvil.log")
    anvil_proc: subprocess.Popen | None = None

    try:
        # 1. Start Anvil
        _step("Starting Anvil on port 8545 ...")
        anvil_proc = _start_anvil(anvil_log)

        # 2. Wait for connection
        _step("Waiting for Anvil to be ready ...")
        w3 = _wait_connected(timeout=10.0)
        _step(f"Connected. Chain ID: {w3.eth.chain_id}")

        accounts = w3.eth.accounts
        deployer = accounts[0]
        voter1, voter2, voter3 = accounts[1], accounts[2], accounts[3]
        _step(f"Deployer:  {deployer}")
        _step(f"Voters:    {voter1}, {voter2}, {voter3}")

        # 3. Compile + deploy
        _step("Compiling and deploying Voting contract ...")
        contract = chain.deploy(w3, deployer)
        _step(f"Contract deployed at {contract.address}")

        # 4. Create election (0,0 = no time window)
        _step("Creating election 'General 2026' ...")
        chain.create_election(contract, deployer, "General 2026", 0, 2**31)

        # 5. Add candidates
        _step("Adding candidates Alice and Bob ...")
        chain.add_candidate(contract, deployer, "Alice")
        chain.add_candidate(contract, deployer, "Bob")

        # 6. Register voters
        _step(f"Registering voters {voter1}, {voter2}, {voter3} ...")
        chain.register_voter(contract, deployer, voter1)
        chain.register_voter(contract, deployer, voter2)
        chain.register_voter(contract, deployer, voter3)

        # 7. Cast votes
        _step("voter1 votes for Alice (index 0) ...")
        chain.cast_vote(contract, voter1, 0)

        _step("voter2 votes for Bob (index 1) ...")
        chain.cast_vote(contract, voter2, 1)

        # 8. Double-vote attempt
        _step("voter1 attempts double-vote — expecting revert 'Already voted' ...")
        double_vote_rejected = False
        try:
            chain.cast_vote(contract, voter1, 0)
        except ContractLogicError as exc:
            assert "Already voted" in str(exc), (
                f"Expected 'Already voted' in revert message, got: {exc}"
            )
            double_vote_rejected = True
            _step("  -> Revert confirmed: 'Already voted'")

        assert double_vote_rejected, "Double-vote was NOT rejected by the contract!"

        # 9. Get results and assert
        _step("Fetching results ...")
        names, counts = chain.get_results(contract)
        _step(f"  Results: {dict(zip(names, counts))}")

        assert names[0] == "Alice", f"Expected 'Alice' at index 0, got '{names[0]}'"
        assert names[1] == "Bob",   f"Expected 'Bob' at index 1, got '{names[1]}'"
        assert counts[0] == 1,      f"Expected Alice=1, got {counts[0]}"
        assert counts[1] == 1,      f"Expected Bob=1, got {counts[1]}"

        cc = chain.candidate_count(contract)
        assert cc == 2, f"Expected candidate_count==2, got {cc}"
        _step(f"  candidate_count == {cc} ✓")

        print()
        print("ALL TESTS PASSED")

    except Exception as exc:
        print(f"\nTEST FAILED: {exc}", file=sys.stderr)
        print(f"Anvil log: {anvil_log}", file=sys.stderr)
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
