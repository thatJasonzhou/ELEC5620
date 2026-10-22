"""Customer quotation projection of trusted FIN-01 handoff records (KAN-25)."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from src.services.vendor_booking_service import quotation_fingerprint
from src.shared.schemas import require_int, require_non_empty_str


def source_fingerprint(event, proposal):
    """Bind the complete JSON event/proposal snapshot, including optional revisions."""
    if not isinstance(event, dict) or not isinstance(proposal, dict):
        raise ValueError("event and proposal must be objects")
    try:
        payload = json.dumps([event, proposal], sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("event and proposal must contain valid JSON") from exc
    return "SF-" + sha256(payload.encode("utf-8")).hexdigest()


def budget_fingerprint(budget):
    """Integrity reference for FIN-01 values; not an authentication signature."""
    fields = ("event_id", "proposal_id", "vendor_total_cents", "service_fee_cents",
              "contingency_cents", "tax_amount_cents", "estimated_total_cents",
              "budget_limit_cents", "within_budget", "over_budget_cents",
              "quotation_fingerprint", "selected_quotation_ids", "budget_valid",
              "price_basis", "required_services", "source_fingerprint")
    payload = json.dumps({key: budget[key] for key in fields}, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return "BF-" + sha256(payload.encode("utf-8")).hexdigest()


class CustomerQuotationService:
    """Validate provenance and copy amounts without invoking pricing or payments."""

    def __init__(self, record_service=None):
        self._records = record_service

    @staticmethod
    def quotation_content(request):
        if not isinstance(request, dict):
            return {"status": "blocked", "message": "request must be an object", "data": {}}
        try:
            event_id = require_non_empty_str(request.get("event_id"), "event_id")
            event, proposal, budget = (request.get(k) for k in ("event", "proposal", "budget"))
            current_source = source_fingerprint(event, proposal)
            proposal_id = require_non_empty_str(proposal.get("proposal_id"), "proposal_id")
            if not isinstance(budget, dict):
                raise ValueError("Validated FIN-01 budget is required")
            if budget.get("budget_valid") is not True or budget.get("within_budget") is not True:
                raise ValueError("Budget must be valid and within budget")
            for record in (event, proposal, budget):
                if record.get("event_id") != event_id:
                    raise ValueError("event_id mismatch")
            if budget.get("proposal_id") != proposal_id:
                raise ValueError("proposal_id mismatch")
            if budget.get("source_fingerprint") != current_source:
                raise ValueError("Budget source changed or missing; validate a fresh FIN-01 budget")
            if budget.get("budget_fingerprint") != budget_fingerprint(budget):
                raise ValueError("Budget contents changed since FIN-01 validation")
            if budget.get("price_basis") != "GST-inclusive":
                raise ValueError("Invalid price basis")
            for key in ("vendor_total_cents", "service_fee_cents", "contingency_cents",
                        "tax_amount_cents", "estimated_total_cents", "budget_limit_cents", "over_budget_cents"):
                require_int(budget.get(key), key)
            selected = request.get("selected_quotation_ids")
            if not isinstance(selected, list) or not selected:
                raise ValueError("selected_quotation_ids must be a non-empty list")
            for identity in selected:
                require_non_empty_str(identity, "selected quotation ID")
            if len(set(selected)) != len(selected) or set(selected) != set(budget["selected_quotation_ids"]):
                raise ValueError("Selected quotation set changed")
            quotes = request.get("quotations")
            if not isinstance(quotes, list) or any(not isinstance(q, dict) for q in quotes):
                raise ValueError("quotations must be a list of objects")
            index = {}
            for q in quotes:
                identity = require_non_empty_str(q.get("quotation_id"), "quotation_id")
                if identity in index:
                    raise ValueError("duplicate quotation_id")
                index[identity] = q
            chosen = [index[identity] for identity in selected]
            if quotation_fingerprint(chosen) != budget["quotation_fingerprint"]:
                raise ValueError("Vendor quotations changed; validate a fresh FIN-01 budget")
            for q in chosen:
                if q["event_id"] != event_id or q["proposal_id"] != proposal_id:
                    raise ValueError("Selected quotation identity mismatch")
                if q["event_date"] != event["event_date"] or q["guest_count"] != event["guest_count"]:
                    raise ValueError("Selected quotation requirements mismatch")
            if set(q["service_type"] for q in chosen) != set(proposal["required_services"]):
                raise ValueError("Required services mismatch")
            # Consistency checks only: fees and prices still come from FIN-01.
            if budget["vendor_total_cents"] != sum(q["quoted_total_cents"] for q in chosen):
                raise ValueError("Budget vendor total is inconsistent")
            if budget["estimated_total_cents"] != sum(budget[k] for k in (
                    "vendor_total_cents", "service_fee_cents", "contingency_cents")):
                raise ValueError("Budget amount breakdown is inconsistent")
            if (budget["tax_amount_cents"] != 0 or budget["over_budget_cents"] != 0
                    or budget["estimated_total_cents"] > budget["budget_limit_cents"]
                    or budget["budget_limit_cents"] != event["budget_limit_cents"]):
                raise ValueError("Budget limits or GST-inclusive tax are inconsistent")
        except (ValueError, TypeError, KeyError) as exc:
            return {"status": "blocked", "message": str(exc), "data": {}}
        quotation = {key: deepcopy(budget[key]) for key in (
            "event_id", "proposal_id", "selected_quotation_ids", "vendor_total_cents",
            "service_fee_cents", "contingency_cents", "tax_amount_cents",
            "estimated_total_cents", "quotation_fingerprint", "source_fingerprint",
            "budget_fingerprint", "price_basis")}
        quotation.update(
                         # Export only primitive fields already validated by
                         # quotation_fingerprint; supplier metadata stays internal.
                         vendor_cost_breakdown=[{key: q[key] for key in (
                             "event_id", "proposal_id", "quotation_id", "vendor_id",
                             "offering_id", "service_type", "event_date", "guest_count",
                             "quoted_total_cents", "available", "mock",
                         )} for q in chosen], currency="AUD")
        return {"status": "success", "message": "Customer quotation validated.",
                "data": {"customer_quotation": quotation}}

    def generate(self, request):
        result = self.quotation_content(request)
        if result["status"] != "success":
            return result
        quotation = result["data"]["customer_quotation"]
        quotation.update(customer_quotation_id="CQ-" + uuid4().hex,
                         generated_at=datetime.now(timezone.utc).isoformat())
        if self._records is not None:
            from src.services.financial_record_service import FinancialStorageError, FinancialRecordConflict
            try:
                quotation = self._records.save_quotation(quotation)
            except FinancialStorageError:
                return dict(status="error", message="Customer quotation storage failed", data={})
            except FinancialRecordConflict as exc:
                return dict(status="blocked", message=str(exc), data={})
        return dict(status="success", message="Customer quotation generated for review.",
                    data={"customer_quotation": quotation})
