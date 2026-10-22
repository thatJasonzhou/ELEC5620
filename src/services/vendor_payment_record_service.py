"""Financial-owned SQLite settlement records. Callers serialize workflows."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3


class VendorPaymentStorageError(RuntimeError):
    pass


class VendorPaymentConflict(ValueError):
    pass


class VendorPaymentRecordService:
    def __init__(self, database_path):
        if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
            raise ValueError("database_path must be a persistent local file")
        if str(database_path) == ":memory:" or str(database_path).startswith("file:"):
            raise ValueError("database_path must be a persistent local file")
        self.database_path = Path(database_path).expanduser().resolve()
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as db, db:
                db.execute('''CREATE TABLE IF NOT EXISTS vendor_payments (
                    payment_id TEXT PRIMARY KEY, vendor_booking_id TEXT NOT NULL UNIQUE,
                    vendor_id TEXT NOT NULL, invoice_number TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','paid','failed')),
                    payload TEXT NOT NULL, UNIQUE(vendor_id, invoice_number))''')
        except (OSError, sqlite3.Error):
            raise VendorPaymentStorageError("Cannot initialize vendor payment storage") from None

    def _connect(self):
        return sqlite3.connect(str(self.database_path), timeout=5)

    def get(self, payment_id):
        return self._read("payment_id", payment_id)

    def get_for_booking(self, booking_id):
        return self._read("vendor_booking_id", booking_id)

    def get_for_event(self, event_id, proposal_id=None):
        """Read existing JSON identities without migrating the KAN-27 table."""
        return read_vendor_payment_history(self.database_path, event_id, proposal_id)

    def _read(self, column, identity):
        try:
            with closing(self._connect()) as db:
                row = db.execute(f"SELECT payload FROM vendor_payments WHERE {column}=?",
                                 (identity,)).fetchone()
            return json.loads(row[0]) if row else None
        except (sqlite3.Error, ValueError, TypeError):
            raise VendorPaymentStorageError("Cannot read vendor payment storage") from None

    def create(self, record):
        try:
            with closing(self._connect()) as db, db:
                db.execute("INSERT INTO vendor_payments VALUES (?,?,?,?,?,?)", (
                    record["payment_id"], record["vendor_booking_id"], record["vendor_id"],
                    record["invoice_number"], record["status"], json.dumps(record, allow_nan=False)))
        except sqlite3.IntegrityError:
            raise VendorPaymentConflict("Booking or vendor invoice already has a payment") from None
        except sqlite3.Error:
            raise VendorPaymentStorageError("Cannot save vendor payment") from None
        return deepcopy(record)

    def finish(self, record):
        if record["status"] not in ("paid", "failed"):
            raise ValueError("Expected terminal payment status")
        try:
            with closing(self._connect()) as db, db:
                changed = db.execute("UPDATE vendor_payments SET status=?, payload=? "
                    "WHERE payment_id=? AND status='pending'", (record["status"],
                    json.dumps(record, allow_nan=False), record["payment_id"])).rowcount
                if changed != 1:
                    raise VendorPaymentConflict("Payment is no longer pending")
        except sqlite3.Error:
            raise VendorPaymentStorageError("Cannot save payment outcome; manual review required") from None
        return deepcopy(record)


def read_vendor_payment_history(database_path, event_id, proposal_id=None):
    """Read-only history projection; an uninitialized vendor module has no records."""
    from src.shared.schemas import require_non_empty_str
    require_non_empty_str(event_id, "event_id")
    if proposal_id is not None:
        require_non_empty_str(proposal_id, "proposal_id")
    try:
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, timeout=5, uri=True)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vendor_payments'").fetchone() is None:
                return []
            records = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM vendor_payments ORDER BY rowid")]
        if any(not isinstance(r, dict) or not isinstance(r.get("event_id"), str)
               or not isinstance(r.get("proposal_id"), str) for r in records):
            raise ValueError("Invalid vendor payment identity")
        return [r for r in records if r["event_id"] == event_id
                and (proposal_id is None or r["proposal_id"] == proposal_id)]
    except (sqlite3.Error, ValueError, TypeError):
        raise VendorPaymentStorageError("Cannot read vendor payment history") from None
