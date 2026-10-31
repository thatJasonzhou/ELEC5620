"""Optional SQLite storage for validated Procurement handoff records.

No payment/approval evidence is stored or authenticated here. Each operation
opens and closes its own connection. Callers must still serialize booking
attempts: SQLite transactions do not make external supplier effects atomic.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from src.shared.schemas import (
    VendorBooking, require_int, require_non_empty_str, require_valid_date,
)


class ProcurementStorageError(RuntimeError):
    """Storage unavailable or a persisted record is invalid."""


class ProcurementRecordConflict(ProcurementStorageError):
    """A saved identity already has different contents; never overwrite it."""


class ProcurementRecordService:
    """Immutable quotation snapshots and confirmed bookings, scoped by IDs.

    Instantiate explicitly to opt in; existing Agents/Services stay in memory.
    Only this Service knows SQL. The database is local prototype storage, not
    an authentication or multi-process workflow coordination mechanism.
    """

    def __init__(self, database_path: str | Path) -> None:
        if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
            raise ValueError("database_path must be a non-empty file path")
        if str(database_path) == ":memory:" or str(database_path).startswith("file:"):
            raise ValueError("database_path must identify a persistent local file")
        self.database_path = Path(database_path).expanduser().resolve()
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection, connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS procurement_quotations (
                    event_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                    quotation_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (event_id, proposal_id, quotation_id))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS procurement_bookings (
                    event_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                    quotation_id TEXT NOT NULL, booking_id TEXT NOT NULL UNIQUE,
                    supplier_confirmation_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                    PRIMARY KEY (event_id, proposal_id, quotation_id))""")
        except (OSError, sqlite3.Error):
            raise ProcurementStorageError("Cannot initialize Procurement storage.") from None

    @classmethod
    def from_env(cls) -> "ProcurementRecordService":
        """ELEC5620_DB_PATH overrides the repository-root runtime default."""
        backend_root = Path(__file__).resolve().parents[2]
        default = backend_root / "runtime" / "procurement.sqlite3"
        configured = os.environ.get("ELEC5620_DB_PATH")
        if configured is None:
            return cls(default)
        if not configured.strip():
            raise ValueError("ELEC5620_DB_PATH must be a non-empty file path")
        path = Path(configured)
        if not path.is_absolute():
            path = backend_root.parent / path
        return cls(path)

    def _connect(self):
        return sqlite3.connect(str(self.database_path), timeout=5)

    @staticmethod
    def _identity(event_id, proposal_id):
        return (require_non_empty_str(event_id, "event_id"),
                require_non_empty_str(proposal_id, "proposal_id"))

    @staticmethod
    def _quote(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("quotation must be an object")
        for name in ("event_id", "proposal_id", "quotation_id", "vendor_id", "offering_id",
                     "service_type", "scenario_id", "recommendation_reason"):
            require_non_empty_str(raw.get(name), name)
        require_valid_date(raw.get("event_date"), "event_date")
        for name in ("guest_count", "quoted_total_cents"):
            require_int(raw.get(name), name, minimum=0)
        if raw.get("available") is not True or raw.get("mock") is not True:
            raise ValueError("only confirmed available mock quotations can be saved")
        return deepcopy(raw)

    @staticmethod
    def _booking(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("booking must be an object")
        # Constructor checks the schema; validators below reject Python's
        # otherwise permissive dataclass argument types.
        item = VendorBooking(**raw)
        for name in ("event_id", "proposal_id", "quotation_id", "booking_id", "vendor_id",
                     "offering_id", "service_type", "supplier_confirmation_id",
                     "source_quotation_fingerprint"):
            require_non_empty_str(getattr(item, name), name)
        require_valid_date(item.event_date, "event_date")
        require_int(item.guest_count, "guest_count", minimum=0)
        require_int(item.quoted_total_cents, "quoted_total_cents", minimum=0)
        if item.status != "Confirmed" or item.mock is not True:
            raise ValueError("only explicitly confirmed mock bookings can be saved")
        return deepcopy(raw)

    @staticmethod
    def _json(record):
        return json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"))

    def save_quotations(self, quotations: list[dict[str, Any]]) -> None:
        """Save a complete validated batch atomically; changed IDs conflict."""
        if not isinstance(quotations, list) or not quotations:
            raise ValueError("quotations must be a non-empty list")
        records = [self._quote(q) for q in quotations]
        identities = [(q["event_id"], q["proposal_id"], q["quotation_id"]) for q in records]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate quotation identity")
        self._save("procurement_quotations", records)

    def save_booking(self, booking: dict[str, Any]) -> None:
        self._save("procurement_bookings", [self._booking(booking)])

    def _save(self, table, records):
        # table is an internal constant, never supplied by a caller.
        try:
            with closing(self._connect()) as connection, connection:
                for record in records:
                    identity = tuple(record[n] for n in ("event_id", "proposal_id", "quotation_id"))
                    payload = self._json(record)
                    if table == "procurement_bookings":
                        connection.execute("""INSERT INTO procurement_bookings
                            (event_id, proposal_id, quotation_id, booking_id, supplier_confirmation_id, payload)
                            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(event_id, proposal_id, quotation_id) DO NOTHING""",
                            (*identity, record["booking_id"], record["supplier_confirmation_id"], payload))
                    else:
                        connection.execute("""INSERT INTO procurement_quotations
                            VALUES (?, ?, ?, ?) ON CONFLICT(event_id, proposal_id, quotation_id) DO NOTHING""",
                            (*identity, payload))
                    saved = connection.execute(
                        f"SELECT payload FROM {table} WHERE event_id=? AND proposal_id=? AND quotation_id=?",
                        identity).fetchone()
                    if saved[0] != payload:
                        raise ProcurementRecordConflict("Saved record differs; review or use a new proposal.")
        except sqlite3.IntegrityError:
            raise ProcurementRecordConflict("Booking/confirmation identity already exists.") from None
        except sqlite3.Error:
            raise ProcurementStorageError("Cannot save Procurement records.") from None

    def get_quotations(self, event_id: str, proposal_id: str) -> list[dict[str, Any]]:
        return self._read("procurement_quotations", self._identity(event_id, proposal_id))

    def get_bookings(self, event_id: str, proposal_id: str) -> list[dict[str, Any]]:
        return self._read("procurement_bookings", self._identity(event_id, proposal_id))

    def all_bookings(self) -> list[dict[str, Any]]:
        """Internal refresh for BookingService's existing all-records accessor."""
        return self._read("procurement_bookings", None)

    def snapshot_event(self, event_id: str) -> dict[str, list[dict[str, Any]]]:
        """Capture this event's local simulated records for classroom recovery."""
        identity = require_non_empty_str(event_id, "event_id")
        return {
            "quotations": [q for q in self._read("procurement_quotations", None)
                           if q["event_id"] == identity],
            "bookings": [b for b in self.all_bookings() if b["event_id"] == identity],
        }

    def restore_event(self, event_id: str, snapshot: dict[str, Any] | None) -> None:
        """Restore one event from a trusted demo snapshot; normal saves stay immutable."""
        identity = require_non_empty_str(event_id, "event_id")
        snapshot = snapshot or {"quotations": [], "bookings": []}
        quotes = [self._quote(q) for q in snapshot["quotations"]]
        bookings = [self._booking(b) for b in snapshot["bookings"]]
        if any(row["event_id"] != identity for row in [*quotes, *bookings]):
            raise ValueError("Procurement checkpoint event_id does not match")
        try:
            with closing(self._connect()) as connection, connection:
                for table in ("procurement_bookings", "procurement_quotations"):
                    connection.execute(f"DELETE FROM {table} WHERE event_id=?", (identity,))
                for row in quotes:
                    connection.execute(
                        "INSERT INTO procurement_quotations VALUES (?, ?, ?, ?)",
                        (identity, row["proposal_id"], row["quotation_id"], self._json(row)),
                    )
                for row in bookings:
                    connection.execute(
                        "INSERT INTO procurement_bookings "
                        "(event_id, proposal_id, quotation_id, booking_id, supplier_confirmation_id, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (identity, row["proposal_id"], row["quotation_id"], row["booking_id"],
                         row["supplier_confirmation_id"], self._json(row)),
                    )
        except sqlite3.Error:
            raise ProcurementStorageError("Cannot restore Procurement demo records.") from None

    def _read(self, table, identity):
        try:
            with closing(self._connect()) as connection:
                sql = f"SELECT event_id, proposal_id, quotation_id, payload FROM {table}"
                if identity is not None:
                    sql += " WHERE event_id=? AND proposal_id=?"
                rows = connection.execute(sql + " ORDER BY event_id, proposal_id, quotation_id",
                                          identity or ()).fetchall()
            records = []
            validate = self._quote if table == "procurement_quotations" else self._booking
            for event_id, proposal_id, quotation_id, payload in rows:
                record = validate(json.loads(payload))
                if (record["event_id"], record["proposal_id"], record["quotation_id"]) != (
                        event_id, proposal_id, quotation_id):
                    raise ValueError("persisted identity mismatch")
                records.append(record)
            return records
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            raise ProcurementStorageError("Cannot read valid Procurement records.") from None
