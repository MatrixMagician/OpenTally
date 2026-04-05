"""OpenTally operator TUI built with Textual.

Screens
-------
PassphraseScreen  – modal that unlocks the SQLCipher database.
OperatorScreen    – main operator interface (election / candidate / voter mgmt).
OpenTallyApp      – root application; orchestrates screen flow.
"""

from __future__ import annotations

import os
from typing import Any

from textual.app import App, ComposeResult
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
)
from textual.containers import Vertical, Horizontal

from opentally import db as _db
from opentally import chain as _chain
from opentally.db import WrongPassphraseError
from web3.exceptions import ContractLogicError

# ---------------------------------------------------------------------------
# Passphrase modal
# ---------------------------------------------------------------------------


class PassphraseScreen(ModalScreen):
    """Unlock the database with a passphrase."""

    DEFAULT_CSS = """
    PassphraseScreen {
        align: center middle;
    }
    #passphrase-dialog {
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #passphrase-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = db_path

    def compose(self) -> ComposeResult:
        with Vertical(id="passphrase-dialog"):
            yield Label("OpenTally — Enter database passphrase")
            yield Input(placeholder="Passphrase", password=True, id="passphrase-input")
            yield Label("", id="passphrase-error")
            yield Button("Unlock", variant="primary", id="passphrase-submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "passphrase-submit":
            self._try_unlock()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._try_unlock()

    def _try_unlock(self) -> None:
        passphrase_input: Input = self.query_one("#passphrase-input", Input)
        error_label: Label = self.query_one("#passphrase-error", Label)
        passphrase = passphrase_input.value.strip()

        try:
            conn = _db.open_db(self._db_path, passphrase)
            _db.create_tables(conn)
        except WrongPassphraseError:
            error_label.update("Wrong passphrase — please try again.")
            passphrase_input.value = ""
            passphrase_input.focus()
            return

        self.dismiss(conn)


# ---------------------------------------------------------------------------
# Operator screen
# ---------------------------------------------------------------------------


class OperatorScreen(Screen):
    """Main operator interface."""

    DEFAULT_CSS = """
    OperatorScreen {
        layout: vertical;
    }
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }
    #left-panel {
        width: 50%;
        padding: 1 2;
    }
    #right-panel {
        width: 50%;
        padding: 1 2;
    }
    .section-title {
        text-style: bold;
        margin-top: 1;
    }
    #status-bar {
        height: 3;
        padding: 0 2;
        background: $surface;
        border-top: solid $primary;
    }
    """

    def __init__(self, conn: Any, rpc_url: str) -> None:
        super().__init__()
        self._conn = conn
        self._rpc_url = rpc_url
        self._current_election_id: int | None = None
        self._contract: Any | None = None  # deployed Contract instance

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield Label("── Create Election ──", classes="section-title")
                yield Input(placeholder="Election name", id="election_name")
                yield Input(placeholder="Start time (unix epoch, 0=none)", id="start_time")
                yield Input(placeholder="End time (unix epoch, 0=none)", id="end_time")
                yield Button("Create Election", variant="primary", id="btn_create_election")

                yield Label("── Add Candidate ──", classes="section-title")
                yield Input(placeholder="Candidate name", id="candidate_name")
                yield Button("Add Candidate", variant="default", id="btn_add_candidate")

                yield Label("── Register Voter ──", classes="section-title")
                yield Input(placeholder="Voter name", id="voter_name")
                yield Input(placeholder="Voter Ethereum address", id="voter_addr")
                yield Button("Register Voter", variant="default", id="btn_register_voter")

                yield Label("── Voting ──", classes="section-title")
                yield Button("Start Voting", variant="success", id="btn_start_voting")
                yield Button("View Results", variant="default", id="btn_view_results")

            with Vertical(id="right-panel"):
                yield Label("── Voters for Current Election ──", classes="section-title")
                yield DataTable(id="voters_table")

        yield Static("Ready.", id="status-bar")

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#voters_table", DataTable)
        table.add_columns("ID", "Name", "Ethereum Address", "Registered At")

    # ------------------------------------------------------------------ helpers

    def update_status(self, message: str) -> None:
        """Update the status bar text (safe to call from thread via call_from_thread)."""
        self.query_one("#status-bar", Static).update(message)

    def _refresh_voters_table(self) -> None:
        """Reload the DataTable from the DB for the current election."""
        table: DataTable = self.query_one("#voters_table", DataTable)
        table.clear()
        if self._current_election_id is None:
            return
        voters = _db.get_voters(self._conn, self._current_election_id)
        for v in voters:
            table.add_row(
                str(v["id"]),
                v["name"],
                v["eth_address"],
                v["registered_at"],
            )

    # ------------------------------------------------------------------ button dispatch

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_create_election":
            self.run_worker(self._create_election, thread=True, exclusive=True)
        elif btn_id == "btn_add_candidate":
            self.run_worker(self._add_candidate, thread=True, exclusive=True)
        elif btn_id == "btn_register_voter":
            self.run_worker(self._register_voter, thread=True, exclusive=True)
        elif btn_id == "btn_start_voting":
            if self._contract is None:
                self.update_status("Create an election first.")
            else:
                self.app.push_screen(
                    VotingScreen(
                        self._conn,
                        self._rpc_url,
                        self._contract,
                        self._current_election_id,
                    )
                )
        elif btn_id == "btn_view_results":
            if self._contract is None:
                self.update_status("No election active.")
            else:
                self.app.push_screen(
                    ResultsScreen(
                        self._conn,
                        self._rpc_url,
                        self._contract,
                        self._current_election_id,
                    )
                )

    # ------------------------------------------------------------------ workers

    def _create_election(self) -> None:
        name = self.query_one("#election_name", Input).value.strip()
        start_str = self.query_one("#start_time", Input).value.strip()
        end_str = self.query_one("#end_time", Input).value.strip()

        if not name:
            self.call_from_thread(self.update_status, "Error: election name is required.")
            return

        try:
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else 0
        except ValueError:
            self.call_from_thread(self.update_status, "Error: start/end times must be integers.")
            return

        try:
            self.call_from_thread(self.update_status, "Connecting to chain…")
            w3 = _chain.connect(self._rpc_url)
            sender = w3.eth.accounts[0]

            self.call_from_thread(self.update_status, "Compiling + deploying contract…")
            contract = _chain.deploy(w3, sender)

            self.call_from_thread(self.update_status, "Sending createElection transaction…")
            _chain.create_election(contract, sender, name, start, end)

            election_id = _db.insert_election(
                self._conn, name, start, end, str(contract.address)
            )
            _db.update_election_contract(self._conn, election_id, str(contract.address))

            self._current_election_id = election_id
            self._contract = contract

            self.call_from_thread(
                self.update_status,
                f"Election '{name}' created (id={election_id}, contract={contract.address}).",
            )
            self.call_from_thread(self._refresh_voters_table)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.update_status, f"Error creating election: {exc}")

    def _add_candidate(self) -> None:
        if self._current_election_id is None or self._contract is None:
            self.call_from_thread(self.update_status, "Error: create an election first.")
            return

        name = self.query_one("#candidate_name", Input).value.strip()
        if not name:
            self.call_from_thread(self.update_status, "Error: candidate name is required.")
            return

        try:
            w3 = _chain.connect(self._rpc_url)
            sender = w3.eth.accounts[0]
            self.call_from_thread(self.update_status, f"Adding candidate '{name}'…")
            _chain.add_candidate(self._contract, sender, name)
            self.call_from_thread(self.update_status, f"Candidate '{name}' added.")
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.update_status, f"Error adding candidate: {exc}")

    def _register_voter(self) -> None:
        if self._current_election_id is None or self._contract is None:
            self.call_from_thread(self.update_status, "Error: create an election first.")
            return

        voter_name = self.query_one("#voter_name", Input).value.strip()
        voter_addr = self.query_one("#voter_addr", Input).value.strip()

        if not voter_name or not voter_addr:
            self.call_from_thread(
                self.update_status, "Error: voter name and address are required."
            )
            return

        try:
            w3 = _chain.connect(self._rpc_url)
            sender = w3.eth.accounts[0]
            self.call_from_thread(self.update_status, f"Registering voter '{voter_name}'…")
            _chain.register_voter(self._contract, sender, voter_addr)
            _db.insert_voter(self._conn, self._current_election_id, voter_name, voter_addr)
            self.call_from_thread(
                self.update_status, f"Voter '{voter_name}' registered."
            )
            self.call_from_thread(self._refresh_voters_table)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.update_status, f"Error registering voter: {exc}")


# ---------------------------------------------------------------------------
# Voting screen
# ---------------------------------------------------------------------------


class VotingScreen(Screen):
    """Allow a registered voter to cast a ballot on-chain."""

    DEFAULT_CSS = """
    VotingScreen {
        align: center middle;
    }
    #vote-dialog {
        width: 70;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #vote-status {
        color: $success;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        conn: Any,
        rpc_url: str,
        contract: Any,
        election_id: int | None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._rpc_url = rpc_url
        self._contract = contract
        self._election_id = election_id

    def compose(self) -> ComposeResult:
        with Vertical(id="vote-dialog"):
            yield Label("── Cast Vote ──")
            yield Label("Select Voter Account:")
            yield Select([], id="voter_select")
            yield Label("Select Candidate:")
            yield Select([], id="candidate_select")
            yield Button("Cast Vote", variant="primary", id="btn_cast_vote")
            yield Static("", id="vote-status")

    def on_mount(self) -> None:
        # Populate voter dropdown from DB
        voter_select: Select = self.query_one("#voter_select", Select)
        if self._election_id is not None:
            voters = _db.get_voters(self._conn, self._election_id)
            voter_options = [
                (f'{v["name"]} ({v["eth_address"][:10]}…)', v["eth_address"])
                for v in voters
            ]
            voter_select.set_options(voter_options)

        # Populate candidate dropdown from chain
        candidate_select: Select = self.query_one("#candidate_select", Select)
        try:
            count = _chain.candidate_count(self._contract)
            cand_options = []
            for i in range(count):
                name, _votes = _chain.get_candidate(self._contract, i)
                cand_options.append((name, i))
            candidate_select.set_options(cand_options)
        except Exception:  # noqa: BLE001
            pass

    def update_vote_status(self, message: str) -> None:
        self.query_one("#vote-status", Static).update(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "btn_cast_vote":
            return

        voter_select: Select = self.query_one("#voter_select", Select)
        candidate_select: Select = self.query_one("#candidate_select", Select)

        voter_addr = voter_select.value
        cand_idx = candidate_select.value

        if voter_addr is Select.BLANK or cand_idx is Select.BLANK:
            self.update_vote_status("✗ Please select both a voter and a candidate.")
            return

        self.run_worker(
            lambda: self._cast_vote(voter_addr, cand_idx),
            thread=True,
            exclusive=True,
        )

    def _cast_vote(self, voter_addr: str, cand_idx: int) -> None:
        try:
            _chain.cast_vote(self._contract, voter_addr, cand_idx)
            # Retrieve candidate name for confirmation message
            try:
                name, _ = _chain.get_candidate(self._contract, cand_idx)
            except Exception:  # noqa: BLE001
                name = str(cand_idx)
            self.call_from_thread(
                self.update_vote_status, f"✓ Vote cast for {name}"
            )
        except ContractLogicError as exc:
            self.call_from_thread(self.update_vote_status, f"✗ {exc}")
        except Exception:
            raise


# ---------------------------------------------------------------------------
# Results screen
# ---------------------------------------------------------------------------


class ResultsScreen(Screen):
    """Display per-candidate tallies, winner, and turnout."""

    DEFAULT_CSS = """
    ResultsScreen {
        align: center middle;
    }
    #results-dialog {
        width: 80;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #winner-label {
        text-style: bold;
        margin-top: 1;
    }
    #turnout-label {
        margin-top: 0;
    }
    #results-status {
        color: $success;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        conn: Any,
        rpc_url: str,
        contract: Any,
        election_id: int | None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._rpc_url = rpc_url
        self._contract = contract
        self._election_id = election_id

    def compose(self) -> ComposeResult:
        with Vertical(id="results-dialog"):
            yield Label("── Election Results ──")
            yield DataTable(id="results-table")
            yield Static("", id="winner-label")
            yield Static("", id="turnout-label")
            yield Static("Loading…", id="results-status")
            yield Button("Back", variant="default", id="btn_back")

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#results-table", DataTable)
        table.add_columns("Candidate", "Votes")
        self.run_worker(self._load_results, thread=True, exclusive=True)

    def _load_results(self) -> None:
        try:
            names, counts = _chain.get_results(self._contract)

            voters = _db.get_voters(self._conn, self._election_id) if self._election_id is not None else []
            num_voters = len(voters)
            total_votes = sum(counts)

            # Compute turnout
            if num_voters > 0:
                turnout = total_votes / num_voters * 100
            else:
                turnout = 0.0
            turnout_text = f"Turnout: {turnout:.1f}% ({total_votes}/{num_voters})"

            # Determine winner
            if not names:
                winner_text = "No candidates."
            else:
                max_count = max(counts)
                winners = [names[i] for i, c in enumerate(counts) if c == max_count]
                if total_votes == 0:
                    winner_text = "No votes cast yet."
                elif len(winners) > 1:
                    winner_text = "Tie: " + ", ".join(winners)
                else:
                    winner_text = "Winner: " + winners[0]

            def _update() -> None:
                table: DataTable = self.query_one("#results-table", DataTable)
                table.clear()
                for name, count in zip(names, counts):
                    table.add_row(name, str(count))
                self.query_one("#winner-label", Static).update(winner_text)
                self.query_one("#turnout-label", Static).update(turnout_text)
                self.query_one("#results-status", Static).update("Loaded.")

            self.call_from_thread(_update)

        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(
                self.query_one("#results-status", Static).update,
                f"Error: {exc}",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_back":
            self.app.pop_screen()


# ---------------------------------------------------------------------------
# Root application
# ---------------------------------------------------------------------------


class OpenTallyApp(App):
    """OpenTally operator TUI."""

    TITLE = "OpenTally"

    def __init__(self) -> None:
        super().__init__()
        self._db_path = os.environ.get("OPENTALLY_DB", "./opentally.db")
        self._rpc_url = os.environ.get("OPENTALLY_RPC", "http://127.0.0.1:8545")
        self._conn: Any = None

    def on_mount(self) -> None:
        self.push_screen(
            PassphraseScreen(self._db_path),
            callback=self._on_passphrase_dismissed,
        )

    def _on_passphrase_dismissed(self, conn: Any) -> None:
        self._conn = conn
        self.push_screen(OperatorScreen(conn, self._rpc_url))
