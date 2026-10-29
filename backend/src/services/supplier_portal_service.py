"""SQLite-backed simulated supplier portal for interactive quotations.

The supplier is still an external-system simulation for Stage 2, but its
reply is entered through the supplier UI instead of being invented by an LLM
or immediately loaded from a preset quotation file.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from src.services.vendor_procurement_service import VendorProcurementService
from src.shared.schemas import require_int, require_non_empty_str, require_valid_date


class SupplierPortalStorageError(RuntimeError):
    """The local supplier portal database cannot be read or written."""


class SupplierPortalService:
    """Persist quote requests and validated supplier replies in SQLite."""

    def __init__(
        self,
        database_path: str | Path,
        vendor_service: VendorProcurementService,
    ) -> None:
        if not isinstance(vendor_service, VendorProcurementService):
            raise TypeError("vendor_service must be a VendorProcurementService")
        if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
            raise ValueError("database_path must be a non-empty file path")
        if str(database_path) == ":memory:" or str(database_path).startswith("file:"):
            raise ValueError("database_path must identify a persistent local file")
        self.database_path = Path(database_path).expanduser().resolve()
        self._vendor_service = vendor_service
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS supplier_quote_requests (
                        request_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        proposal_id TEXT NOT NULL,
                        vendor_id TEXT NOT NULL,
                        offering_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        request_payload TEXT NOT NULL,
                        response_payload TEXT,
                        created_at TEXT NOT NULL,
                        responded_at TEXT,
                        UNIQUE(event_id, proposal_id, vendor_id, offering_id)
                    )"""
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS supplier_final_confirmations (
                        confirmation_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        proposal_id TEXT NOT NULL,
                        vendor_id TEXT NOT NULL,
                        offering_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        request_payload TEXT NOT NULL,
                        response_payload TEXT,
                        created_at TEXT NOT NULL,
                        responded_at TEXT,
                        UNIQUE(event_id, proposal_id, vendor_id, offering_id)
                    )"""
                )
        except (OSError, sqlite3.Error):
            raise SupplierPortalStorageError(
                "Cannot initialize supplier portal storage."
            ) from None

    @classmethod
    def from_env(
        cls, vendor_service: VendorProcurementService
    ) -> "SupplierPortalService":
        backend_root = Path(__file__).resolve().parents[2]
        configured = os.environ.get("SUPPLIER_PORTAL_DB_PATH")
        if configured is None:
            path = backend_root / "runtime" / "supplier_portal.sqlite3"
        else:
            if not configured.strip():
                raise ValueError("SUPPLIER_PORTAL_DB_PATH must be non-empty")
            path = Path(configured)
            if not path.is_absolute():
                path = backend_root.parent / path
        return cls(path, vendor_service)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def list_vendors(self) -> list[dict[str, Any]]:
        """Return catalogue identities for the prototype vendor selector."""
        result = []
        for vendor in self._vendor_service.catalog:
            result.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "vendor_name": vendor.name,
                    "service_types": sorted(
                        {offering.service_type for offering in vendor.service_offerings}
                    ),
                }
            )
        return result

    def create_quote_requests(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create an idempotent batch of RFQs from verified catalogue matches."""
        if not isinstance(requests, list) or not requests:
            raise ValueError("requests must be a non-empty list")
        records = [self._validate_request(item) for item in requests]
        scopes = {(item["event_id"], item["proposal_id"]) for item in records}
        if len(scopes) != 1:
            raise ValueError("one request batch must belong to one event proposal")
        identities = [
            (
                item["event_id"], item["proposal_id"],
                item["vendor_id"], item["offering_id"],
            )
            for item in records
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate supplier quote request")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                for item in records:
                    identity_json = json.dumps(
                        [item["event_id"], item["proposal_id"],
                         item["vendor_id"], item["offering_id"]],
                        separators=(",", ":"),
                    )
                    request_id = "RFQ-" + sha256(
                        identity_json.encode("utf-8")
                    ).hexdigest()[:20].upper()
                    payload = self._json(item)
                    connection.execute(
                        """INSERT INTO supplier_quote_requests
                        (request_id, event_id, proposal_id, vendor_id,
                         offering_id, status, request_payload, created_at)
                        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                        ON CONFLICT(event_id, proposal_id, vendor_id, offering_id)
                        DO NOTHING""",
                        (request_id, item["event_id"], item["proposal_id"],
                         item["vendor_id"], item["offering_id"], payload, now),
                    )
                    saved = connection.execute(
                        """SELECT request_payload FROM supplier_quote_requests
                        WHERE event_id=? AND proposal_id=? AND vendor_id=?
                        AND offering_id=?""",
                        (item["event_id"], item["proposal_id"],
                         item["vendor_id"], item["offering_id"]),
                    ).fetchone()
                    if saved is None or saved["request_payload"] != payload:
                        raise ValueError(
                            "An existing supplier request has different event details"
                        )
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot save supplier quote requests."
            ) from None
        event_id, proposal_id = next(iter(scopes))
        return self.list_quote_requests(event_id=event_id, proposal_id=proposal_id)

    def list_quote_requests(
        self,
        *,
        vendor_id: str | None = None,
        event_id: str | None = None,
        proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        for field, value in (("vendor_id", vendor_id), ("event_id", event_id),
                             ("proposal_id", proposal_id)):
            if value is not None:
                clauses.append(f"{field}=?")
                values.append(require_non_empty_str(value, field))
        sql = "SELECT * FROM supplier_quote_requests"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, request_id"
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(sql, values).fetchall()
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot read supplier quote requests."
            ) from None
        return [self._row_to_record(row) for row in rows]

    def respond_to_quote_request(
        self,
        request_id: str,
        *,
        available: bool,
        quoted_total_cents: int | None,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Accept with an actual price or decline one pending RFQ."""
        request_id = require_non_empty_str(request_id, "request_id")
        if not isinstance(available, bool):
            raise ValueError("available must be a boolean")
        if available:
            cents = require_int(quoted_total_cents, "quoted_total_cents", minimum=1)
        else:
            if quoted_total_cents is not None:
                raise ValueError("a declined request must not include a price")
            cents = None
        clean_message = (message or "").strip()
        if len(clean_message) > 500:
            raise ValueError("message must be at most 500 characters")
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT * FROM supplier_quote_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise KeyError("supplier quote request not found")
                if row["status"] != "pending":
                    raise ValueError("this supplier quote request has already been answered")
                request = json.loads(row["request_payload"])
                status = "quoted" if available else "declined"
                public_status = "accepted" if available else "rejected"
                reason = clean_message or (
                    "Supplier confirmed availability and submitted this price."
                    if available else "Supplier is not available for this request."
                )
                quote_identity = self._json([request_id, public_status, cents])
                response = {
                    "mock": True,
                    "source": "vendor_portal",
                    "quotation_id": "VQ-" + sha256(
                        quote_identity.encode("utf-8")
                    ).hexdigest()[:24].upper(),
                    "scenario_id": request_id,
                    "request_id": request_id,
                    "event_id": request["event_id"],
                    "proposal_id": request["proposal_id"],
                    "vendor_id": request["vendor_id"],
                    "offering_id": request["offering_id"],
                    "event_date": request["event_date"],
                    "guest_count": request["guest_count"],
                    "status": public_status,
                    "available": available,
                    "quoted_total_cents": cents,
                    "reason": reason,
                }
                responded_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """UPDATE supplier_quote_requests
                    SET status=?, response_payload=?, responded_at=?
                    WHERE request_id=?""",
                    (status, self._json(response), responded_at, request_id),
                )
                updated = connection.execute(
                    "SELECT * FROM supplier_quote_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot save the supplier response."
            ) from None
        return self._row_to_record(updated)

    def create_confirmation_requests(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create conditional pre-deposit confirmation requests."""
        if not isinstance(requests, list) or not requests:
            raise ValueError("confirmation requests must be a non-empty list")
        records = [self._validate_confirmation(item) for item in requests]
        scopes = {(item["event_id"], item["proposal_id"]) for item in records}
        if len(scopes) != 1:
            raise ValueError("one confirmation batch must belong to one proposal")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                for item in records:
                    identity = self._json(
                        [item["event_id"], item["proposal_id"], item["quotation_id"]]
                    )
                    confirmation_id = "SCF-" + sha256(
                        identity.encode("utf-8")
                    ).hexdigest()[:20].upper()
                    payload = self._json(item)
                    connection.execute(
                        """INSERT INTO supplier_final_confirmations
                        (confirmation_id, event_id, proposal_id, vendor_id,
                         offering_id, status, request_payload, created_at)
                        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                        ON CONFLICT(event_id, proposal_id, vendor_id, offering_id)
                        DO NOTHING""",
                        (
                            confirmation_id, item["event_id"], item["proposal_id"],
                            item["vendor_id"], item["offering_id"], payload, now,
                        ),
                    )
                    saved = connection.execute(
                        """SELECT request_payload FROM supplier_final_confirmations
                        WHERE event_id=? AND proposal_id=? AND vendor_id=? AND offering_id=?""",
                        (
                            item["event_id"], item["proposal_id"],
                            item["vendor_id"], item["offering_id"],
                        ),
                    ).fetchone()
                    if saved is None or saved["request_payload"] != payload:
                        raise ValueError("An existing confirmation has different details")
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot save supplier confirmation requests."
            ) from None
        event_id, proposal_id = next(iter(scopes))
        return self.list_confirmation_requests(
            event_id=event_id, proposal_id=proposal_id
        )

    def list_confirmation_requests(
        self,
        *,
        event_id: str | None = None,
        proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        for field, value in (("event_id", event_id), ("proposal_id", proposal_id)):
            if value is not None:
                clauses.append(f"{field}=?")
                values.append(require_non_empty_str(value, field))
        sql = "SELECT * FROM supplier_final_confirmations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, confirmation_id"
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(sql, values).fetchall()
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot read supplier confirmation requests."
            ) from None
        return [self._confirmation_row(row) for row in rows]

    def respond_to_confirmation(
        self,
        confirmation_id: str,
        *,
        confirmed: bool,
        message: str | None = None,
    ) -> dict[str, Any]:
        confirmation_id = require_non_empty_str(
            confirmation_id, "confirmation_id"
        )
        if not isinstance(confirmed, bool):
            raise ValueError("confirmed must be a boolean")
        clean_message = (message or "").strip()
        if len(clean_message) > 500:
            raise ValueError("message must be at most 500 characters")
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT * FROM supplier_final_confirmations WHERE confirmation_id=?",
                    (confirmation_id,),
                ).fetchone()
                if row is None:
                    raise KeyError("supplier confirmation request not found")
                if row["status"] != "pending":
                    raise ValueError("this confirmation has already been answered")
                request = json.loads(row["request_payload"])
                status = "confirmed" if confirmed else "declined"
                response = {
                    "mock": True,
                    "source": "vendor_portal",
                    "confirmation_id": confirmation_id,
                    "event_id": request["event_id"],
                    "proposal_id": request["proposal_id"],
                    "quotation_id": request["quotation_id"],
                    "vendor_id": request["vendor_id"],
                    "offering_id": request["offering_id"],
                    "status": status,
                    "confirmed": confirmed,
                    "reason": clean_message or (
                        "Supplier conditionally confirmed the booking pending deposit."
                        if confirmed
                        else "Supplier can no longer accept this booking."
                    ),
                }
                responded_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """UPDATE supplier_final_confirmations
                    SET status=?, response_payload=?, responded_at=?
                    WHERE confirmation_id=?""",
                    (status, self._json(response), responded_at, confirmation_id),
                )
                updated = connection.execute(
                    "SELECT * FROM supplier_final_confirmations WHERE confirmation_id=?",
                    (confirmation_id,),
                ).fetchone()
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot save the supplier confirmation response."
            ) from None
        return self._confirmation_row(updated)

    def clear_all_quote_requests(self) -> int:
        """Clear all simulated RFQs, confirmations and replies."""
        try:
            with closing(self._connect()) as connection, connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM supplier_quote_requests"
                ).fetchone()[0]
                count += connection.execute(
                    "SELECT COUNT(*) FROM supplier_final_confirmations"
                ).fetchone()[0]
                connection.execute("DELETE FROM supplier_quote_requests")
                connection.execute("DELETE FROM supplier_final_confirmations")
        except sqlite3.Error:
            raise SupplierPortalStorageError(
                "Cannot reset supplier portal cases."
            ) from None
        return int(count)

    @staticmethod
    def _validate_request(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("supplier request must be an object")
        result = {}
        for name in (
            "event_id", "proposal_id", "vendor_id", "vendor_name",
            "offering_id", "service_type", "event_summary", "event_type",
            "arrival_time", "service_start_time", "service_end_time", "location",
        ):
            result[name] = require_non_empty_str(raw.get(name), name)
        result["event_date"] = require_valid_date(raw.get("event_date"), "event_date")
        for name in ("guest_count", "catalogue_estimate_cents"):
            result[name] = require_int(raw.get(name), name, minimum=0)
        return result

    @staticmethod
    def _validate_confirmation(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("confirmation request must be an object")
        result: dict[str, Any] = {}
        for name in (
            "event_id", "proposal_id", "customer_quotation_id", "quotation_id",
            "vendor_id", "vendor_name", "offering_id", "service_type",
            "event_date", "arrival_time", "service_start_time", "service_end_time",
        ):
            result[name] = require_non_empty_str(raw.get(name), name)
        require_valid_date(result["event_date"], "event_date")
        result["quoted_total_cents"] = require_int(
            raw.get("quoted_total_cents"), "quoted_total_cents", minimum=1
        )
        return result

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":"))

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        request = json.loads(row["request_payload"])
        response = (json.loads(row["response_payload"])
                    if row["response_payload"] is not None else None)
        return {
            **deepcopy(request),
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "responded_at": row["responded_at"],
            "response": response,
        }

    @staticmethod
    def _confirmation_row(row: sqlite3.Row) -> dict[str, Any]:
        request = json.loads(row["request_payload"])
        response = (
            json.loads(row["response_payload"])
            if row["response_payload"] is not None
            else None
        )
        return {
            **deepcopy(request),
            "confirmation_id": row["confirmation_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "responded_at": row["responded_at"],
            "response": response,
        }
