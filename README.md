# OpenTally

A secure, Ethereum-based voting system with an encrypted local database and a terminal user interface. An operator creates elections, registers candidates and voter wallet addresses, and voters cast ballots — recorded immutably on a local Ethereum chain. Voter PII is stored in an AES-256 encrypted SQLCipher database keyed to an operator passphrase. Results are displayed with the winner, per-candidate vote counts, and turnout percentage.

## Features

- **On-chain vote integrity** — votes are stored in a Solidity smart contract; the blockchain enforces one-vote-per-address, not the UI
- **Double-vote prevention** — the contract rejects any second vote from a registered address with a hard revert
- **Encrypted voter database** — voter names and Ethereum addresses stored in an AES-256 SQLCipher database, unlocked at startup by an operator passphrase
- **Full TUI** — keyboard-navigable Textual interface covering the complete election lifecycle:
  - `PassphraseScreen` — unlock the encrypted database at startup
  - `OperatorScreen` — create elections, add candidates, register voters, navigate to voting and results
  - `VotingScreen` — select voter and candidate, cast ballot, see immediate confirmation or rejection
  - `ResultsScreen` — per-candidate tallies, winner (or tie), turnout percentage

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | ≥ 3.10 | Tested on 3.13 |
| [Anvil (Foundry)](https://book.getfoundry.sh/getting-started/installation) | latest | Local Ethereum node — must be on `$PATH` as `anvil` |
| sqlcipher3 | system lib + Python package | See installation notes below |

### Installing Anvil

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

Verify: `anvil --version`

### Installing sqlcipher3

sqlcipher3 requires the native SQLCipher library.

**macOS (Homebrew):**
```bash
brew install sqlcipher
pip install sqlcipher3
```

**Ubuntu / Debian:**
```bash
sudo apt-get install libsqlcipher-dev
pip install sqlcipher3
```

**Arch Linux:**
```bash
sudo pacman -S sqlcipher
pip install sqlcipher3
```

## Installation

```bash
git clone https://github.com/MatrixMagician/OpenTally.git
cd OpenTally
pip install -r requirements.txt
```

> `py-solc-x` will automatically download Solidity 0.8.20 the first time the contract is compiled.

## Running the App

```bash
python3 -m opentally
```

You will be prompted for a passphrase on first run. This passphrase encrypts the local voter database — **do not lose it**; there is no recovery mechanism.

Set `OPENTALLY_DB` (default: `opentally.db`) and `OPENTALLY_RPC` (default: `http://127.0.0.1:8545`) environment variables to customise paths:

```bash
OPENTALLY_DB=/secure/path/voters.db OPENTALLY_RPC=http://127.0.0.1:8545 python3 -m opentally
```

## Running the Tests

Each test script is standalone — it spawns its own Anvil instance, so no manual setup is required.

```bash
python3 tests/test_contract.py   # Smart contract + double-vote prevention
python3 tests/test_db.py         # SQLCipher encryption and CRUD
python3 tests/test_s02.py        # Election management end-to-end
python3 tests/test_s03.py        # Voting flow end-to-end
python3 tests/test_s04.py        # Results screen end-to-end
```

All tests should exit with code `0` and print a `PASSED` summary.

## Project Structure

```
contracts/
  Voting.sol          # Solidity 0.8.20 voting contract
opentally/
  __init__.py
  __main__.py         # Entry point: python3 -m opentally
  chain.py            # web3.py bridge — compile, deploy, contract wrappers
  db.py               # SQLCipher CRUD — elections, voters, passphrase auth
  app.py              # Textual TUI — all four screens
tests/
  test_contract.py    # Contract unit + double-vote test
  test_db.py          # DB encryption test
  test_s02.py         # Election management integration test
  test_s03.py         # Voting flow integration test
  test_s04.py         # Results screen integration test
requirements.txt
```

## Architecture

- **Smart contract:** Solidity 0.8.20 (`contracts/Voting.sol`) — single-election-per-deployment; `createElection`, `addCandidate`, `registerVoter`, `castVote`, `getResults`
- **Chain:** Anvil local Ethereum node, connected via HTTP JSON-RPC
- **Web3 bridge:** web3.py ≥ 7.0 — synchronous; all calls wrapped in `thread=True` Textual workers to avoid blocking the asyncio event loop
- **Database:** SQLCipher via `sqlcipher3` — AES-256 at rest; passphrase-derived key set at startup via `PRAGMA key`
- **TUI:** Textual ≥ 0.50 — multi-screen with `call_from_thread` for safe cross-thread UI updates

## Known Limitations

- **Single election per deployment** — calling `createElection` resets the contract state. A new Anvil session starts fresh each time; past elections are queryable from the SQLCipher DB only.
- **Local chain only** — the app targets a local Anvil node. Deploying to a real testnet or mainnet requires additional configuration (infura/alchemy RPC URL, funded wallet, gas estimation).
- **No auto-refresh on ResultsScreen** — vote counts are fetched once on mount. Navigate away and back to refresh.
- **Passphrase not recoverable** — if the passphrase is lost, the SQLCipher DB cannot be decrypted.

## License

See [LICENSE](LICENSE).
