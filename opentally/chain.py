"""web3.py bridge for the Voting smart contract."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.contract import Contract

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_SOL_FILE = str(_ROOT / "contracts" / "Voting.sol")


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def compile_contract() -> tuple[list[dict], str]:
    """Return (abi, bytecode) for contracts/Voting.sol.

    Installs solc 0.8.20 on first call if not already present.
    """
    import solcx  # type: ignore

    try:
        solcx.set_solc_version("0.8.20", silent=True)
    except Exception:
        solcx.install_solc("0.8.20", show_progress=False)
        solcx.set_solc_version("0.8.20", silent=True)

    compiled = solcx.compile_files(
        [_SOL_FILE],
        solc_version="0.8.20",
        output_values=["abi", "bin"],
    )
    key = next(k for k in compiled if k.endswith(":Voting"))
    abi = compiled[key]["abi"]
    bytecode = compiled[key]["bin"]
    return abi, bytecode


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def connect(rpc_url: str = "http://127.0.0.1:8545") -> Web3:
    """Return a connected Web3 instance pointing at *rpc_url*."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    return w3


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------


def deploy(w3: Web3, deployer_address: str) -> Contract:
    """Compile and deploy the Voting contract; return a bound Contract."""
    abi, bytecode = compile_contract()
    VotingContract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = VotingContract.constructor().transact({"from": deployer_address})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return w3.eth.contract(address=receipt["contractAddress"], abi=abi)


# ---------------------------------------------------------------------------
# Thin wrappers
# ---------------------------------------------------------------------------


def create_election(
    contract: Contract,
    sender: str,
    name: str,
    start: int = 0,
    end: int = 0,
) -> Any:
    tx = contract.functions.createElection(name, start, end).transact(
        {"from": sender}
    )
    return contract.w3.eth.wait_for_transaction_receipt(tx)


def add_candidate(contract: Contract, sender: str, name: str) -> Any:
    tx = contract.functions.addCandidate(name).transact({"from": sender})
    return contract.w3.eth.wait_for_transaction_receipt(tx)


def register_voter(contract: Contract, sender: str, voter: str) -> Any:
    tx = contract.functions.registerVoter(voter).transact({"from": sender})
    return contract.w3.eth.wait_for_transaction_receipt(tx)


def cast_vote(contract: Contract, voter: str, candidate_index: int) -> Any:
    """Cast a vote; lets ContractLogicError propagate on revert."""
    tx = contract.functions.castVote(candidate_index).transact({"from": voter})
    return contract.w3.eth.wait_for_transaction_receipt(tx)


def get_results(
    contract: Contract,
) -> tuple[list[str], list[int]]:
    names, counts = contract.functions.getResults().call()
    return list(names), [int(c) for c in counts]


def candidate_count(contract: Contract) -> int:
    return int(contract.functions.candidateCount().call())


def get_candidate(contract: Contract, idx: int) -> tuple[str, int]:
    name, count = contract.functions.getCandidate(idx).call()
    return name, int(count)
