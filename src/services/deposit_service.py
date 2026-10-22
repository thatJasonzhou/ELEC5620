"""Explicit customer deposit workflow over trusted current Integration snapshots.

Records are detached; optional SQLite storage protects restart retries.
No cross-process exactly-once payment guarantee. Integration must supply current approval on every operation.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from threading import RLock
from uuid import uuid4

from src.financial_config import deposit_rate
from src.services.financial_record_service import deposit_content, quotation_content, canonical
from src.services.customer_quotation_service import CustomerQuotationService
from src.services.mock_payment_service import MockPaymentService
from src.shared.schemas import CustomerPayment, require_int, require_non_empty_str, require_valid_date


class DepositService:
    def __init__(self, payment_service, record_service=None):
        if not isinstance(payment_service, MockPaymentService):
            raise TypeError("DepositService requires an explicit MockPaymentService")
        self._payments = payment_service
        self._records = record_service
        self._requests = {}
        self._keys = {}
        self._lock = RLock()

    @property
    def records(self):
        with self._lock:
            if self._records is not None:
                return deepcopy([r["deposit"] for r in self._records.all_deposits()
                                 if r["deposit"]["status"] == "paid"])
            return deepcopy([r["deposit"] for r in self._requests.values()
                             if r["deposit"]["status"] == "paid"])

    def _validate(self, request):
        result = CustomerQuotationService.quotation_content(request)
        if result["status"] != "success":
            raise ValueError(result["message"])
        current = result["data"]["customer_quotation"]
        quote = request.get("customer_quotation")
        if not isinstance(quote, dict):
            raise ValueError("customer_quotation is required")
        require_non_empty_str(quote.get("customer_quotation_id"), "customer_quotation_id")
        require_non_empty_str(quote.get("generated_at"), "generated_at")
        generated = datetime.fromisoformat(quote["generated_at"])
        if generated.utcoffset() is None:
            raise ValueError("Customer quotation generated_at must include timezone")
        for key in ("vendor_total_cents", "service_fee_cents", "contingency_cents",
                    "tax_amount_cents", "estimated_total_cents"):
            require_int(quote.get(key), key)
        for key, value in current.items():
            if key not in ("customer_quotation_id", "generated_at") and quote.get(key) != value:
                raise ValueError("Customer quotation changed or inconsistent: " + key)
        approval = request.get("approval")
        if not isinstance(approval, dict) or approval.get("approved") is not True:
            raise ValueError("Explicit current customer Approval is required")
        for key in ("event_id", "proposal_id", "quotation_fingerprint", "customer_quotation_id"):
            if approval.get(key) != quote[key]:
                raise ValueError("Approval mismatch: " + key)
        ids = approval.get("approved_quotation_ids")
        if (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)
                or len(ids) != len(set(ids)) or set(ids) != set(quote["selected_quotation_ids"])):
            raise ValueError("Approval must cover exactly the selected quotations")
        require_non_empty_str(request.get("customer_id"), "customer_id")
        require_valid_date(request.get("due_date"), "due_date")
        return quote

    def prepare(self, request):
        return self._run(request, False)

    def simulate_payment(self, request):
        return self._run(request, True)

    def _run(self, request, pay):
        with self._lock:
            try:
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                quote = self._validate(request)
                if not pay:
                    rate = deposit_rate()
                    with localcontext() as ctx:
                        ctx.prec = max(28, len(str(quote["estimated_total_cents"])) + len(rate.as_tuple().digits) + 4)
                        due = int((Decimal(quote["estimated_total_cents"]) * rate).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP))
                    require_int(due, "deposit_due_cents", minimum=1)
                    identity = (quote["customer_quotation_id"], request["customer_id"])
                    token = "DR-" + uuid4().hex
                    now = datetime.now(timezone.utc).isoformat()
                    deposit = {key: quote[key] for key in (
                        "event_id", "proposal_id", "quotation_fingerprint", "customer_quotation_id")}
                    deposit.update(deposit_request_id=token, payment_id="CP-" + uuid4().hex,
                                   amount_cents=due, status="pending", mock=True, created_at=now)
                    saved = dict(quote=deepcopy(quote), customer_id=request["customer_id"],
                                 due_date=request["due_date"], deposit=deposit,
                                 budget={**deepcopy(request["budget"]), "deposit_due_cents": due})
                    saved["execution_state"] = "not_started"
                    if self._records is not None:
                        saved = self._records.create_deposit(saved)
                    elif identity in self._keys:
                        previous = self._requests[self._keys[identity]]
                        if canonical(deposit_content(previous)) != canonical(deposit_content(saved)):
                            raise ValueError("Existing deposit request conflicts; review required")
                        saved = previous
                    token = saved["deposit"]["deposit_request_id"]
                    self._requests[token] = saved
                    self._keys[identity] = token
                    return self._result(saved)
                if request.get("simulate") is not True:
                    raise ValueError("Explicit simulate=true payment request is required")
                token = require_non_empty_str(request.get("deposit_request_id"), "deposit_request_id")
                saved = (self._records.get_deposit(token) if self._records is not None
                         else deepcopy(self._requests.get(token)))
                if saved is None:
                    raise ValueError("Unknown deposit_request_id")
                deposit = saved["deposit"]
                amount = require_int(request.get("amount_cents"), "amount_cents", minimum=1)
                if (saved["quote"]["customer_quotation_id"] != quote["customer_quotation_id"]
                        or canonical(quotation_content(saved["quote"])) != canonical(quotation_content(quote))
                        or saved["customer_id"] != request["customer_id"]
                        or saved["due_date"] != request["due_date"] or amount != deposit["amount_cents"]):
                    raise ValueError("Deposit request, quotation, customer or amount mismatch")
                if deposit["status"] == "paid":
                    return self._result(saved)
                if saved.get("execution_state", "not_started") != "not_started":
                    raise RuntimeError("Payment execution uncertain; reconciliation required")
                payment = CustomerPayment(payment_id=deposit["payment_id"], event_id=deposit["event_id"],
                    amount_cents=amount, created_at=datetime.fromisoformat(deposit["created_at"]),
                    status="pending", customer_id=saved["customer_id"], payment_type="deposit",
                    due_date=date.fromisoformat(saved["due_date"]))
                if self._records is not None:
                    self._records.start_execution(token)
                saved["execution_state"] = "execution_started"
                self._requests[token] = deepcopy(saved)
                try:
                    reply = self._payments.process_payment(payment)
                except Exception:
                    self._mark_uncertain(token)
                    raise RuntimeError("Payment execution uncertain; reconciliation required") from None
                if (not isinstance(reply, dict) or reply.get("status") != "paid" or reply.get("mock") is not True
                        or reply.get("payment_id") != payment.payment_id
                        or type(reply.get("amount_cents")) is not int or reply["amount_cents"] != amount):
                    self._mark_uncertain(token)
                    raise RuntimeError("Mock payment did not return matching successful evidence")
                try:
                    reference = require_non_empty_str(reply.get("transaction_reference"), "transaction_reference")
                except ValueError:
                    self._mark_uncertain(token)
                    raise RuntimeError("Missing payment evidence; reconciliation required") from None
                deposit.update(status="paid", paid_at=datetime.now(timezone.utc).isoformat(),
                               transaction_reference=reference)
                saved["execution_state"] = "result_recorded"
                try:
                    if self._records is not None:
                        self._records.finish_execution(saved)
                except (RuntimeError, ValueError):
                    self._mark_uncertain(token)
                    raise RuntimeError("Cannot save payment outcome; reconciliation required") from None
                self._requests[token] = deepcopy(saved)
                return self._result(saved)
            except (ValueError, KeyError, TypeError) as exc:
                return dict(status="blocked", message=str(exc), data={})
            except (OSError, RuntimeError) as exc:
                return dict(status="error", message="Mock deposit operation failed; review required", data={})

    def _mark_uncertain(self, token):
        if token in self._requests:
            self._requests[token]["execution_state"] = "requires_reconciliation"
        if self._records is not None:
            self._records.require_reconciliation(token)

    @staticmethod
    def _result(saved):
        return dict(status="success", message="Mock customer deposit " + saved["deposit"]["status"],
                    data=deepcopy({"deposit": saved["deposit"], "budget": saved["budget"]}))
