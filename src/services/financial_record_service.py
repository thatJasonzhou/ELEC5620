"""KAN-29 internal SQLite snapshots and conservative deposit execution journal."""
from contextlib import closing, contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime

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
                    "paid_at", "transaction_reference", "failed_at", "failure_reason")})


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
                db.execute('''CREATE TABLE IF NOT EXISTS financial_final_requests (
                    request_id TEXT PRIMARY KEY, payment_id TEXT NOT NULL UNIQUE,
                    event_id TEXT NOT NULL, customer_id TEXT NOT NULL,
                    payload TEXT NOT NULL, execution_state TEXT NOT NULL CHECK(
                    execution_state IN ('prepared','executing','completed','stale','requires_reconciliation')) )''')
                db.execute('''CREATE TABLE IF NOT EXISTS customer_collection_claims (
                    event_id TEXT NOT NULL, customer_id TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE, PRIMARY KEY(event_id,customer_id))''')
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
            identity = result.get("deposit", result.get("payment", result))
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
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT schema_version,payload FROM financial_deposits WHERE deposit_request_id=?", (token,)).fetchone()
            if row is None:
                raise FinancialRecordConflict("Unknown deposit request")
            record = self._decode(row)
            self._claim(db, record, token, record['deposit']['amount_cents'], final=False)
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
            if record["deposit"]["status"] not in ("paid", "failed"):
                raise ValueError("Terminal payment evidence required")
            changed = db.execute("UPDATE financial_deposits SET payload=?, execution_state='result_recorded' "
                "WHERE deposit_request_id=? AND execution_state='execution_started'",
                (canonical(record), record["deposit"]["deposit_request_id"])).rowcount
            if changed != 1:
                raise FinancialRecordConflict("Payment execution state conflicts")
            db.execute("DELETE FROM customer_collection_claims WHERE request_id=?", (record['deposit']['deposit_request_id'],))
            if record['deposit']['status'] == 'paid':
                self._stale_prepared(db, record)

    def require_reconciliation(self, token):
        with self._db() as db:
            db.execute("UPDATE financial_deposits SET execution_state='requires_reconciliation' "
                       "WHERE deposit_request_id=? AND execution_state='execution_started'", (token,))

    def _collections(self, db, event_id, customer_id):
        records = []
        for row in db.execute("SELECT schema_version,payload,execution_state FROM financial_deposits WHERE event_id=? AND customer_id=?", (event_id, customer_id)):
            record = self._decode(row)
            records.append((record['deposit'], row[2], record))
        for payload, state in db.execute("SELECT payload,execution_state FROM financial_final_requests WHERE event_id=? AND customer_id=?", (event_id, customer_id)):
            record = self._decode((1, payload))
            records.append((record['payment'], state, record))
        return records

    @staticmethod
    def _stale_prepared(db, record):
        db.execute("UPDATE financial_final_requests SET execution_state='stale' "
                   "WHERE event_id=? AND customer_id=? AND execution_state='prepared'",
                   (record['quote']['event_id'], record['customer_id']))

    def _balance(self, db, quote, customer_id):
        paid = {}
        for payment, state, _ in self._collections(db, quote['event_id'], customer_id):
            if payment['status'] != 'paid':
                continue
            # A status string alone is never successful payment evidence.
            try:
                valid = (state in ('result_recorded', 'completed')
                         and payment.get('mock') is True
                         and type(payment['amount_cents']) is int and payment['amount_cents'] > 0
                         and payment.get('transaction_reference') == 'MOCK-' + payment['payment_id']
                         and datetime.fromisoformat(payment['paid_at']).utcoffset() is not None)
            except (KeyError, ValueError, TypeError):
                valid = False
            if not valid:
                raise FinancialRecordConflict('Invalid successful customer payment evidence; review required')
            identity = payment['payment_id']
            evidence = (payment['amount_cents'], payment['transaction_reference'])
            if identity in paid and paid[identity] != evidence:
                raise FinancialRecordConflict('Conflicting duplicate payment evidence')
            paid[identity] = evidence
        total = quote['estimated_total_cents']
        confirmed = sum(p[0] for p in paid.values())
        if confirmed > total:
            raise FinancialRecordConflict('Confirmed payments exceed approved quotation; review required')
        return dict(event_id=quote['event_id'], customer_id=customer_id,
                    customer_quotation_id=quote['customer_quotation_id'], currency='AUD',
                    quotation_total_cents=total, paid_total_cents=confirmed,
                    balance_cents=total-confirmed)

    def customer_balance(self, quote, customer_id):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._balance(db, quote, customer_id)

    @contextmanager
    def reconciliation_snapshot(self):
        """Existing database only; one read transaction for all financial evidence."""
        try:
            uri = self.database_path.as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                yield db
                db.rollback()
        except (sqlite3.Error, OSError, json.JSONDecodeError):
            raise FinancialStorageError('Cannot read reconciliation snapshot') from None

    def event_funds(self, event_id):
        """Activity-wide durable receipts and vendor expenditure, across revisions.

        Serialized demo workflows only; this read does not reserve funds.
        """
        from src.services.vendor_payment_record_service import read_vendor_payment_history
        from src.shared.schemas import require_int
        require_non_empty_str(event_id, 'event_id')
        collections = []
        with self._db() as db:
            customers = db.execute('SELECT customer_id FROM financial_deposits WHERE event_id=? '
                'UNION SELECT customer_id FROM financial_final_requests WHERE event_id=?',
                (event_id, event_id)).fetchall()
            for (customer,) in customers:
                collections.extend((p, state, customer) for p, state, _ in
                                   self._collections(db, event_id, customer))
        vendors = read_vendor_payment_history(self.database_path, event_id)

        def total(items):
            paid = {}
            for payment, state, owner in items:
                if payment.get('status') != 'paid':
                    continue
                try:
                    identity = require_non_empty_str(payment.get('payment_id'), 'payment_id')
                    amount = require_int(payment.get('amount_cents'), 'amount_cents', minimum=1)
                    if (state not in ('result_recorded', 'completed')
                            or payment.get('event_id') != event_id
                            or payment.get('mock') is not True
                            or payment.get('currency', 'AUD') != 'AUD'
                            or payment.get('transaction_reference') != 'MOCK-' + identity
                            or datetime.fromisoformat(payment['paid_at']).utcoffset() is None):
                        raise ValueError('Invalid paid evidence')
                    evidence = (amount, owner)
                    if identity in paid and paid[identity] != evidence:
                        raise ValueError('Conflicting duplicate paid evidence')
                    paid[identity] = evidence
                except (KeyError, ValueError, TypeError):
                    raise FinancialRecordConflict('Invalid successful payment evidence; review required') from None
            return sum(item[0] for item in paid.values())

        received = total(collections)
        spent = total((p, 'completed', p.get('vendor_booking_id')) for p in vendors)
        if spent > received:
            raise FinancialRecordConflict('Vendor expenditure exceeds recorded receipts; review required')
        return dict(event_id=event_id, currency='AUD', received_total_cents=received,
                    vendor_paid_total_cents=spent, available_funds_cents=received-spent)

    def _claim(self, db, record, token, amount, *, final):
        quote, customer = record['quote'], record['customer_id']
        event = quote['event_id']
        if db.execute('SELECT 1 FROM customer_collection_claims WHERE event_id=? AND customer_id=?', (event, customer)).fetchone():
            raise FinancialRecordConflict('Customer collection executing or requires reconciliation')
        for _, state, _ in self._collections(db, event, customer):
            if state in ('execution_started', 'executing', 'requires_reconciliation'):
                raise FinancialRecordConflict('Customer collection executing or requires reconciliation')
        balance = self._balance(db, quote, customer)['balance_cents']
        if amount > balance or (final and amount != balance):
            raise FinancialRecordConflict('Payment amount no longer matches available balance')
        db.execute('INSERT INTO customer_collection_claims VALUES (?,?,?)', (event, customer, token))

    def prepare_final(self, record):
        payment = record['payment']
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            balance = self._balance(db, record['quote'], record['customer_id'])
            existing = None
            for old, state, saved in self._collections(db, payment['event_id'], record['customer_id']):
                if 'final_request_id' not in old:
                    continue
                if state in ('executing', 'requires_reconciliation'):
                    raise FinancialRecordConflict('Customer collection requires reconciliation')
                if state == 'completed' and old['status'] == 'failed':
                    raise FinancialRecordConflict('Failed payment is terminal; no new payment attempt supported')
                if state != 'prepared':
                    continue
                valid = (old['amount_cents'] == balance['balance_cents']
                         and canonical(saved['quote']) == canonical(record['quote']))
                if not valid:
                    db.execute("UPDATE financial_final_requests SET execution_state='stale' WHERE request_id=?", (old['final_request_id'],))
                else:
                    if saved['due_date'] != record['due_date']:
                        raise FinancialRecordConflict('Existing final request due_date conflicts')
                    existing = saved
            if existing:
                return existing, balance
            if balance['balance_cents'] == 0:
                return None, balance
            payment['amount_cents'] = balance['balance_cents']
            db.execute('INSERT INTO financial_final_requests VALUES (?,?,?,?,?,?)',
                       (payment['final_request_id'], payment['payment_id'], payment['event_id'],
                        record['customer_id'], canonical(record), 'prepared'))
        return deepcopy(record), balance

    def get_final(self, token):
        with self._db() as db:
            row = db.execute('SELECT payload,execution_state FROM financial_final_requests WHERE request_id=?', (token,)).fetchone()
            if row is None:
                return None
            result = self._decode((1, row[0]))
            result['execution_state'] = row[1]
            return result

    def start_final(self, token):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,execution_state FROM financial_final_requests WHERE request_id=?', (token,)).fetchone()
            if row is None or row[1] != 'prepared':
                raise FinancialRecordConflict('Final request is not prepared')
            record = self._decode((1, row[0]))
            amount = record['payment']['amount_cents']
            if amount != self._balance(db, record['quote'], record['customer_id'])['balance_cents']:
                db.execute("UPDATE financial_final_requests SET execution_state='stale' WHERE request_id=?", (token,))
                return False
            self._claim(db, record, token, amount, final=True)
            db.execute("UPDATE financial_final_requests SET execution_state='executing' WHERE request_id=?", (token,))
        return True

    def finish_final(self, record):
        token = record['payment']['final_request_id']
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,execution_state FROM financial_final_requests WHERE request_id=?', (token,)).fetchone()
            if row is None or row[1] != 'executing':
                raise FinancialRecordConflict('Final execution state conflicts')
            original = self._decode((1, row[0]))
            immutable = lambda r: {**r, 'execution_state': None, 'payment': {
                k: v for k, v in r['payment'].items() if k not in
                ('status', 'paid_at', 'failed_at', 'transaction_reference', 'failure_reason')}}
            if canonical(immutable(original)) != canonical(immutable(record)):
                raise FinancialRecordConflict('Final request immutable contents conflict')
            if record['payment']['status'] not in ('paid', 'failed'):
                raise FinancialRecordConflict('Terminal payment evidence required')
            db.execute("UPDATE financial_final_requests SET payload=?,execution_state='completed' WHERE request_id=?", (canonical(record), token))
            db.execute('DELETE FROM customer_collection_claims WHERE request_id=?', (token,))
            if record['payment']['status'] == 'paid':
                self._stale_prepared(db, record)

    def uncertain_final(self, token):
        with self._db() as db:
            db.execute("UPDATE financial_final_requests SET execution_state='requires_reconciliation' WHERE request_id=? AND execution_state='executing'", (token,))

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
        with self._db() as db:
            result['final_payments'] = []
            for payload, state in db.execute('SELECT payload,execution_state FROM financial_final_requests WHERE event_id=? ORDER BY rowid', (event_id,)):
                saved = self._decode((1, payload))
                saved['execution_state'] = state
                if proposal_id is None or saved['payment']['proposal_id'] == proposal_id:
                    result['final_payments'].append(saved)
        return result
