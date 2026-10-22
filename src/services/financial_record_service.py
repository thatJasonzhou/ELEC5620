"""KAN-29 internal SQLite snapshots and conservative deposit execution journal."""
from contextlib import closing, contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3

from src.shared.schemas import require_non_empty_str


class FinancialStorageError(RuntimeError):
    pass


class FinancialRecordConflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def quotation_content(record):
    return {k: v for k, v in record.items()
            if k not in ("customer_quotation_id", "generated_at")}


def deposit_content(record):
    d = record["deposit"]
    return dict(customer_id=record["customer_id"], due_date=record["due_date"],
                quote_id=record["quote"]["customer_quotation_id"],
                quote=quotation_content(record["quote"]), budget=record["budget"],
                deposit={k: v for k, v in d.items() if k not in (
                    "deposit_request_id", "payment_id", "created_at", "status",
                    "paid_at", "transaction_reference")})


class FinancialRecordService:
    def __init__(self, database_path):
        if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
            raise ValueError("Persistent database path required")
        if str(database_path) == ":memory:" or str(database_path).startswith("file:"):
            raise ValueError("Persistent database path required")
        self.database_path = Path(database_path).expanduser().resolve()
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._db() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS financial_snapshots (
                    kind TEXT NOT NULL, identity TEXT NOT NULL,
                    record_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                    content TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(kind, identity), UNIQUE(kind, record_id))''')
                db.execute('''CREATE TABLE IF NOT EXISTS financial_deposits (
                    deposit_request_id TEXT PRIMARY KEY, payment_id TEXT NOT NULL UNIQUE,
                    quotation_id TEXT NOT NULL, customer_id TEXT NOT NULL,
                    event_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL, content TEXT NOT NULL,
                    payload TEXT NOT NULL, execution_state TEXT NOT NULL CHECK(
                    execution_state IN ('not_started','execution_started',
                    'result_recorded','requires_reconciliation')),
                    UNIQUE(quotation_id, customer_id))''')
        except OSError:
            raise FinancialStorageError("Cannot initialize financial storage") from None

    @classmethod
    def from_env(cls):
        default = Path(__file__).resolve().parents[2] / "runtime" / "procurement.sqlite3"
        return cls(os.environ.get("ELEC5620_DB_PATH", str(default)))

    @contextmanager
    def _db(self):
        try:
            with closing(sqlite3.connect(str(self.database_path), timeout=5)) as db, db:
                yield db
        except (sqlite3.Error, OSError, json.JSONDecodeError):
            raise FinancialStorageError("Financial storage operation failed; review required") from None

    @staticmethod
    def _decode(row):
        if row[0] != 1:
            raise FinancialStorageError("Unsupported financial schema version")
        try:
            result = json.loads(row[1])
            if not isinstance(result, dict):
                raise ValueError()
            identity = result.get("deposit", result)
            require_non_empty_str(identity.get("event_id"), "event_id")
            require_non_empty_str(identity.get("proposal_id"), "proposal_id")
            return result
        except (ValueError, TypeError, AttributeError):
            raise FinancialStorageError("Invalid financial snapshot") from None

    def save_budget(self, record):
        return self._snapshot("budget", record["budget_fingerprint"],
                              record["budget_fingerprint"], record, record)

    def save_quotation(self, record):
        return self._snapshot("customer_quotation", record["budget_fingerprint"],
                              record["customer_quotation_id"], record, quotation_content(record))

    def _snapshot(self, kind, identity, record_id, record, content):
        business = canonical(content)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT schema_version,payload,content FROM financial_snapshots "
                             "WHERE kind=? AND (identity=? OR record_id=?)",
                             (kind, identity, record_id)).fetchone()
            if row:
                if row[2] != business:
                    raise FinancialRecordConflict("Financial snapshot identity conflicts")
                return self._decode(row)
            db.execute("INSERT INTO financial_snapshots VALUES (?,?,?,?,?,?,?,?)",
                       (kind, identity, record_id, record["event_id"], record["proposal_id"],
                        1, business, canonical(record)))
        return deepcopy(record)

    def create_deposit(self, record):
        d = record["deposit"]
        business = canonical(deposit_content(record))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT schema_version,payload,content FROM financial_deposits "
                "WHERE (quotation_id=? AND customer_id=?) OR deposit_request_id=? OR payment_id=?",
                (record["quote"]["customer_quotation_id"], record["customer_id"],
                 d["deposit_request_id"], d["payment_id"])).fetchone()
            if row:
                if row[2] != business:
                    raise FinancialRecordConflict("Deposit immutable contents conflict")
                return self._decode(row)
            db.execute("INSERT INTO financial_deposits VALUES (?,?,?,?,?,?,?,?,?,?)",
                (d["deposit_request_id"], d["payment_id"], record["quote"]["customer_quotation_id"],
                 record["customer_id"], d["event_id"], d["proposal_id"], 1, business,
                 canonical(record), "not_started"))
        return deepcopy(record)

    def get_deposit(self, token):
        with self._db() as db:
            row = db.execute("SELECT schema_version,payload,execution_state FROM financial_deposits "
                             "WHERE deposit_request_id=?", (token,)).fetchone()
            if row is None:
                return None
            record = self._decode(row)
            record["execution_state"] = row[2]
            return record

    def all_deposits(self):
        with self._db() as db:
            return [self._decode(row) for row in db.execute(
                "SELECT schema_version,payload FROM financial_deposits ORDER BY rowid")]

    def start_execution(self, token):
        with self._db() as db:
            changed = db.execute("UPDATE financial_deposits SET execution_state='execution_started' "
                "WHERE deposit_request_id=? AND execution_state='not_started'", (token,)).rowcount
            if changed != 1:
                raise FinancialRecordConflict("Payment execution uncertain; reconciliation required")

    def finish_execution(self, record):
        with self._db() as db:
            row = db.execute("SELECT schema_version,payload,content FROM financial_deposits WHERE deposit_request_id=?",
                             (record["deposit"]["deposit_request_id"],)).fetchone()
            if row is None or row[2] != canonical(deposit_content(record)):
                raise FinancialRecordConflict("Deposit immutable contents conflict")
            original = self._decode(row)["deposit"]
            if any(original[key] != record["deposit"][key] for key in (
                    "deposit_request_id", "payment_id", "created_at")):
                raise FinancialRecordConflict("Deposit original identity or timestamp conflicts")
            if record["deposit"]["status"] != "paid":
                raise ValueError("Successful paid evidence required")
            changed = db.execute("UPDATE financial_deposits SET payload=?, execution_state='result_recorded' "
                "WHERE deposit_request_id=? AND execution_state='execution_started'",
                (canonical(record), record["deposit"]["deposit_request_id"])).rowcount
            if changed != 1:
                raise FinancialRecordConflict("Payment execution state conflicts")

    def require_reconciliation(self, token):
        with self._db() as db:
            db.execute("UPDATE financial_deposits SET execution_state='requires_reconciliation' "
                       "WHERE deposit_request_id=? AND execution_state='execution_started'", (token,))

    def get_event_records(self, event_id, proposal_id=None):
        require_non_empty_str(event_id, "event_id")
        if proposal_id is not None:
            require_non_empty_str(proposal_id, "proposal_id")
        where = "event_id=?" + (" AND proposal_id=?" if proposal_id is not None else "")
        args = (event_id,) if proposal_id is None else (event_id, proposal_id)
        result = dict(budgets=[], customer_quotations=[], deposits=[])
        with self._db() as db:
            for row in db.execute("SELECT schema_version,payload,kind FROM financial_snapshots WHERE "
                                  + where + " ORDER BY rowid", args):
                result["budgets" if row[2] == "budget" else "customer_quotations"].append(self._decode(row))
            for row in db.execute("SELECT schema_version,payload,execution_state FROM financial_deposits WHERE "
                                  + where + " ORDER BY rowid", args):
                r = self._decode(row)
                r["execution_state"] = row[2]
                result["deposits"].append(r)
        return result

    def get_event_financial_records(self, event_id, proposal_id=None):
        from src.services.vendor_payment_record_service import read_vendor_payment_history
        result = self.get_event_records(event_id, proposal_id)
        result["vendor_payments"] = read_vendor_payment_history(
            self.database_path, event_id, proposal_id)
        return result
