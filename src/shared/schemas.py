"""Shared dataclasses for the vendor catalog (Stage 2, KAN-15).

These are minimal example structures for the vendor filtering feature.
They intentionally do NOT reproduce the complete Stage 1 class
definitions; the field conventions follow shared-data-and-interfaces.md
(snake_case, integer AUD cents, dates in YYYY-MM-DD).

Mapping (Stage 1 names, minimal scope):
- Vendor                 -> vendor identity + its service offerings
- VendorServiceOffering  -> one service a vendor can deliver (type,
                            location, capacity, rating, whole-event price)
- VendorAvailability     -> one available date slot on an offering

Loading is strict: wrong types (bools where ints are required, float
cents, string booleans, invalid dates) raise ValueError instead of
being silently coerced.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# Operations minimal domain model (KAN-28). No duplicate vendor models.
TASK_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "DELAYED", "COMPLETED")


@dataclass
class OperationalTask:
    """Stage 1 task; title/scheduled_at are the shared JSON aliases."""

    task_id: str
    task_name: str
    planned_start_time: str
    planned_end_time: str
    booking_id: str | None = None
    status: str = "NOT_STARTED"
    delay_reason: str | None = None

    def update_status(self, status: str, reason: str | None = None) -> None:
        allowed = {
            "NOT_STARTED": ("NOT_STARTED", "IN_PROGRESS", "DELAYED"),
            "IN_PROGRESS": ("IN_PROGRESS", "DELAYED", "COMPLETED"),
            "DELAYED": ("DELAYED", "IN_PROGRESS", "COMPLETED"),
            "COMPLETED": ("COMPLETED",),
        }
        if status not in allowed[self.status]:
            raise ValueError("Invalid task transition; completed tasks cannot be reopened.")
        if status == "DELAYED":
            require_non_empty_str(reason, "delay reason")
        self.status = status
        # Preserve the last reported reason for review after resumption.
        if status == "DELAYED":
            self.delay_reason = reason

    def start(self) -> None:
        self.update_status("IN_PROGRESS")

    def complete(self) -> None:
        self.update_status("COMPLETED")

    def report_delay(self, reason: str) -> None:
        self.update_status("DELAYED", reason)

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "title": self.task_name,
                "scheduled_at": self.planned_start_time,
                "planned_end_time": self.planned_end_time,
                "booking_id": self.booking_id, "status": self.status,
                "delay_reason": self.delay_reason}


@dataclass
class ExecutionPlan:
    """One active plan per event, composing its tasks (Stage 1)."""

    event_id: str
    proposal_id: str
    execution_plan_id: str
    tasks: list[OperationalTask] = field(default_factory=list)

    def add_task(self, task: OperationalTask) -> None:
        if any(t.task_id == task.task_id for t in self.tasks):
            raise ValueError("Duplicate task_id")
        self.tasks.append(task)

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "proposal_id": self.proposal_id,
                "execution_plan_id": self.execution_plan_id,
                "tasks": [task.to_dict() for task in self.tasks]}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_vendor_evidence(request):
    """Validate explicit mock evidence; Procurement matching belongs to Service."""
    from copy import deepcopy
    from datetime import timezone
    invoice, completion = request.get("invoice"), request.get("completion")
    if not isinstance(invoice, dict) or not isinstance(completion, dict):
        raise ValueError("Structured invoice and completion objects are required")
    for item in (invoice, completion):
        for key in ("event_id", "proposal_id", "vendor_booking_id", "quotation_id", "vendor_id"):
            require_non_empty_str(item.get(key), key)
            if item[key] != invoice.get(key):
                raise ValueError("Invoice/completion mismatch: " + key)
        for key in ("event_id", "proposal_id"):
            if item[key] != request.get(key):
                raise ValueError("Evidence request mismatch: " + key)
        if item.get("mock") is not True:
            raise ValueError("Evidence must be explicitly mock")
    require_non_empty_str(invoice.get("invoice_number"), "invoice_number")
    require_int(invoice.get("amount_cents"), "amount_cents", minimum=1)
    require_valid_date(invoice.get("issued_date"), "issued_date")
    if invoice.get("currency") != "AUD":
        raise ValueError("Invoice currency must be AUD")
    require_non_empty_str(completion.get("completion_id"), "completion_id")
    if completion.get("status") != "completed":
        raise ValueError("Service must be completed")
    completed = datetime.fromisoformat(require_non_empty_str(completion.get("completed_at"), "completed_at"))
    if completed.utcoffset() is None or completed > datetime.now(timezone.utc):
        raise ValueError("completed_at must be timezone-aware and not in the future")
    return deepcopy(invoice), deepcopy(completion)


def require_non_empty_str(value: Any, field_name: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got {value!r}")
    return value


def require_valid_date(value: Any, field_name: str) -> str:
    """Return ``value`` if it is a real calendar date in YYYY-MM-DD."""
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be a YYYY-MM-DD date string, "
            f"got {type(value).__name__}: {value!r}"
        )
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format, got {value!r}"
        )
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{field_name} is not a valid calendar date: {value!r}"
        ) from None
    return value


def require_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    """Return ``value`` if it is an int (bools rejected) and >= minimum."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be an integer, "
            f"got {type(value).__name__}: {value!r}"
        )
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}, got {value}")
    return value


def require_number(value: Any, field_name: str) -> float:
    """Return ``value`` as float if it is a number (bools rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a number, "
            f"got {type(value).__name__}: {value!r}"
        )
    return float(value)


@dataclass
class VendorAvailability:
    """One availability slot on a service offering.

    ``date`` uses the shared format ``YYYY-MM-DD``.
    """

    date: str
    available: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VendorAvailability":
        if not isinstance(data, dict):
            raise ValueError(
                "availability slot must be an object, "
                f"got {type(data).__name__}: {data!r}"
            )
        return cls(
            date=require_valid_date(data.get("date"), "availability.date"),
            available=cls._require_available(data.get("available", True)),
        )

    @staticmethod
    def _require_available(value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(
                "availability.available must be a boolean, "
                f"got {type(value).__name__}: {value!r}"
            )
        return value


@dataclass
class VendorServiceOffering:
    """A service a vendor offers for a whole event.

    ``total_price_cents`` is the whole-event price in integer AUD cents.
    """

    offering_id: str
    service_type: str
    service_location: str
    guest_capacity: int
    rating: float
    total_price_cents: int
    availability: list[VendorAvailability] = field(default_factory=list)

    def is_available_on(self, date: str) -> bool:
        return any(slot.date == date and slot.available for slot in self.availability)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VendorServiceOffering":
        if not isinstance(data, dict):
            raise ValueError(
                "service offering must be an object, "
                f"got {type(data).__name__}: {data!r}"
            )
        raw_availability = data.get("availability", [])
        if not isinstance(raw_availability, list):
            raise ValueError(
                "offering.availability must be a list of availability slots, "
                f"got {type(raw_availability).__name__}"
            )
        return cls(
            offering_id=require_non_empty_str(
                data.get("offering_id"), "offering.offering_id"
            ),
            service_type=require_non_empty_str(
                data.get("service_type"), "offering.service_type"
            ),
            service_location=require_non_empty_str(
                data.get("service_location"), "offering.service_location"
            ),
            guest_capacity=require_int(
                data.get("guest_capacity"), "offering.guest_capacity", minimum=0
            ),
            rating=require_number(data.get("rating"), "offering.rating"),
            total_price_cents=require_int(
                data.get("total_price_cents"),
                "offering.total_price_cents",
                minimum=0,
            ),
            availability=[
                VendorAvailability.from_dict(slot) for slot in raw_availability
            ],
        )


@dataclass
class Vendor:
    """A fictional vendor in the catalog."""

    vendor_id: str
    name: str
    service_offerings: list[VendorServiceOffering] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vendor":
        if not isinstance(data, dict):
            raise ValueError(
                f"vendor must be an object, got {type(data).__name__}: {data!r}"
            )
        raw_offerings = data.get("service_offerings", [])
        if not isinstance(raw_offerings, list):
            raise ValueError(
                "vendor.service_offerings must be a list of offerings, "
                f"got {type(raw_offerings).__name__}"
            )
        return cls(
            vendor_id=require_non_empty_str(data.get("vendor_id"), "vendor.vendor_id"),
            name=require_non_empty_str(data.get("name"), "vendor.name"),
            service_offerings=[
                VendorServiceOffering.from_dict(offer) for offer in raw_offerings
            ],
        )


@dataclass
class VendorBooking:
    """Minimal confirmed mock booking handoff (KAN-20), not a full Stage 1 model."""

    event_id: str
    proposal_id: str
    booking_id: str
    quotation_id: str
    vendor_id: str
    status: str
    offering_id: str
    service_type: str
    event_date: str
    guest_count: int
    quoted_total_cents: int
    supplier_confirmation_id: str
    source_quotation_fingerprint: str
    mock: bool = True


@dataclass
class Budget:
    """Financial record for GST-inclusive budget calculation.

    UML mapping: budgetId:String -> budget_id:str; eventId:int -> event_id:str.
    Decimal vendorCost, contingencyAmount, taxAmount and customerPrice map to
    integer AUD vendor_cost_cents, contingency_amount_cents, tax_amount_cents
    and customer_price_cents respectively. No Decimal conversion is performed.
    BudgetStatus is temporarily a non-empty string, without a default.

    UML Event (1) -- Budget (0..1), Budget (1) -- EventProposal (1), and
    Budget (1) aggregating VendorQuotation (1..*) are not enforced here.
    Approved V1 adds service_fee_cents; tax_amount_cents remains a zero placeholder.
    """

    budget_id: str
    event_id: str
    vendor_cost_cents: int
    contingency_amount_cents: int
    tax_amount_cents: int
    customer_price_cents: int
    status: str

    # Company service fee, calculated from selected vendor costs.
    service_fee_cents: int = 0

    def __post_init__(self) -> None:
        for name in ("budget_id", "event_id", "status"):
            require_non_empty_str(getattr(self, name), name)
        for name in ("vendor_cost_cents", "contingency_amount_cents",
                     "tax_amount_cents", "customer_price_cents", "service_fee_cents"):
            require_int(getattr(self, name), name)

    def add_vendor_quotation(self, quotation: Any) -> None:
        """Aggregate validated mock Procurement snapshots for this event."""
        from copy import deepcopy
        if not isinstance(quotation, dict):
            raise ValueError("quotation must be an object")
        for name in ("quotation_id", "event_id", "proposal_id", "vendor_id", "offering_id", "service_type"):
            require_non_empty_str(quotation.get(name), name)
        require_valid_date(quotation.get("event_date"), "event_date")
        require_int(quotation.get("guest_count"), "guest_count")
        require_int(quotation.get("quoted_total_cents"), "quoted_total_cents")
        if quotation.get("available") is not True or quotation.get("mock") is not True:
            raise ValueError("quotation must be available and explicitly mock")
        existing = getattr(self, "_selected_quotations", [])
        quotes = [*existing, deepcopy(quotation)]
        if len({q["quotation_id"] for q in quotes}) != len(quotes):
            raise ValueError("duplicate quotation_id")
        if len({(q["vendor_id"], q["offering_id"], q["event_date"]) for q in quotes}) != len(quotes):
            raise ValueError("duplicate selected offering")
        if quotation["event_id"] != self.event_id:
            raise ValueError("quotation event_id mismatch")
        if existing and quotation["proposal_id"] != existing[0]["proposal_id"]:
            raise ValueError("quotation proposal_id mismatch")
        self._selected_quotations = quotes
        self.vendor_cost_cents = sum(q["quoted_total_cents"] for q in quotes)

    def calculate_total(self) -> int:
        """Compute independent 10% fees using exact ROUND_HALF_UP cents.

        tax_amount_cents=0 is the approved no-separate-tax-detail placeholder.
        All costs already include GST; nothing is added for tax.
        """
        if not getattr(self, "_selected_quotations", None):
            raise ValueError("Budget requires selected quotations before calculation")
        vendor = sum(require_int(q["quoted_total_cents"], "quoted_total_cents")
                     for q in self._selected_quotations)
        if type(self.tax_amount_cents) is not int or self.tax_amount_cents != 0:
            raise ValueError("tax_amount_cents must be the approved zero placeholder")
        from src.shared.costing import calculate_event_costs

        costs = calculate_event_costs(vendor)
        self.vendor_cost_cents = costs["vendor_cost_cents"]
        self.service_fee_cents = costs["service_fee_cents"]
        self.contingency_amount_cents = costs["contingency_amount_cents"]
        self.customer_price_cents = costs["customer_price_cents"]
        return self.customer_price_cents

    def approve(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: Budget.approve")

    def revise(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: Budget.revise")


@dataclass(kw_only=True)
class Payment(ABC):
    """Abstract financial record, with no payment processing or transitions.

    UML mapping: paymentId:String -> payment_id:str; eventId:int -> event_id:str;
    amount:Decimal -> amount_cents:int (AUD, no conversion layer).
    createdAt/paidAt:DateTime -> created_at/paid_at:datetime;
    transactionReference:String -> transaction_reference:str.
    PaymentStatus -> status:str, validated only as a non-empty string.
    None represents facts that have not occurred; no timestamps are generated.
    Event (1) -- Payment (0..*) is recorded by event_id, not enforced here.
    """

    payment_id: str
    event_id: str
    amount_cents: int
    created_at: datetime
    status: str
    paid_at: datetime | None = None
    transaction_reference: str | None = None

    def __post_init__(self) -> None:
        for name in ("payment_id", "event_id", "status"):
            require_non_empty_str(getattr(self, name), name)
        require_int(self.amount_cents, "amount_cents")
        self._validate_datetime(self.created_at, "created_at")
        if self.paid_at is not None:
            self._validate_datetime(self.paid_at, "paid_at")
        if self.transaction_reference is not None:
            require_non_empty_str(self.transaction_reference, "transaction_reference")

    @staticmethod
    def _validate_datetime(value: datetime, name: str) -> None:
        # Shared handoff conventions require datetime values with a UTC offset.
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError(f"{name} must be a timezone-aware datetime")

    @abstractmethod
    def initiate(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: Payment.initiate")

    @abstractmethod
    def confirm(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: Payment.confirm")

    @abstractmethod
    def fail(self, reason: str) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: Payment.fail")


@dataclass(kw_only=True)
class CustomerPayment(Payment):
    """Customer payment data, not a simulated or verified transaction.

    UML customerId:int -> customer_id:str; paymentType:CustomerPaymentType
    -> payment_type:str (non-empty, no enum/default); dueDate:Date -> due_date:date.
    Customer (1) -- CustomerPayment (0..*) is not enforced by this model.
    The pending/paid/failed deposit handoff is NOT mapped to UML Confirmed.
    """

    customer_id: str
    payment_type: str
    due_date: date

    def __post_init__(self) -> None:
        super().__post_init__()
        require_non_empty_str(self.customer_id, "customer_id")
        require_non_empty_str(self.payment_type, "payment_type")
        if not isinstance(self.due_date, date) or isinstance(self.due_date, datetime):
            raise ValueError("due_date must be a date, not a datetime")
        require_valid_date(self.due_date.isoformat(), "due_date")

    def initiate(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: CustomerPayment.initiate")

    def confirm(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: CustomerPayment.confirm")

    def fail(self, reason: str) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: CustomerPayment.fail")

    def record_payment(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: CustomerPayment.record_payment")

    def verify_amount(self) -> bool:
        raise NotImplementedError("NOT_IMPLEMENTED: CustomerPayment.verify_amount")


@dataclass(kw_only=True)
class VendorPayment(Payment):
    """Vendor payment data; no invoice validation or settlement is performed.

    UML vendorId:int -> vendor_id:str; vendorBookingId:int -> vendor_booking_id:str;
    invoiceNumber:String -> invoice_number:str; approvedAt:DateTime
    -> approved_at:datetime | None. No approval timestamp is generated.
    Vendor (1) -- VendorPayment (0..*) and VendorBooking (1) -- VendorPayment
    (0..1) remain UML relationships; uniqueness is not enforced here.
    """

    vendor_id: str
    vendor_booking_id: str
    invoice_number: str
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("vendor_id", "vendor_booking_id", "invoice_number"):
            require_non_empty_str(getattr(self, name), name)
        if self.approved_at is not None:
            self._validate_datetime(self.approved_at, "approved_at")

    def initiate(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.initiate")

    def confirm(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.confirm")

    def fail(self, reason: str) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.fail")

    def validate_invoice(self) -> bool:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.validate_invoice")

    def approve_settlement(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.approve_settlement")

    def mark_paid(self) -> None:
        raise NotImplementedError("NOT_IMPLEMENTED: VendorPayment.mark_paid")
