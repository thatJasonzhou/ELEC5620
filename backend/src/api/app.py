"""HTTP API connecting React to the Stage 2 multi-agent workflow."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agents import (
    EventOperationsAgent,
    EventPlannerAgent,
    FinancialManagerAgent,
    VendorProcurementManagerAgent,
)
from src.llm import DemoLLMClient, LLMError, OpenAIResponsesClient
from src.services.event_session_service import EventSessionService
from src.services.event_operations_service import EventOperationsService
from src.services.financial_workflow_service import FinancialWorkflowService
from src.services.planner_workflow_service import PlannerWorkflowService
from src.services.procurement_record_service import ProcurementRecordService
from src.services.supplier_portal_service import (
    SupplierPortalService,
    SupplierPortalStorageError,
)
from src.services.vendor_booking_service import (
    MockVendorBookingService,
    VendorBookingService,
)
from src.services.vendor_procurement_service import VendorProcurementService
from src.services.vendor_quotation_service import MockVendorQuotationService


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT.parent / ".env")


class PlannerMessageRequest(BaseModel):
    event_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class QuotationSelectionRequest(BaseModel):
    quotation_ids: list[str] = Field(min_length=1)


class SupplierQuoteResponseRequest(BaseModel):
    available: bool
    quoted_total_cents: int | None = Field(default=None, ge=1)
    message: str | None = Field(default=None, max_length=500)


class SupplierConfirmationResponseRequest(BaseModel):
    confirmed: bool
    message: str | None = Field(default=None, max_length=500)


class OperationsActionRequest(BaseModel):
    task_id: str | None = None
    expected_arrival_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    reason: str | None = Field(default=None, max_length=500)
    minutes: int | None = None
    issue_id: str | None = None
    resolution: str | None = Field(default=None, max_length=500)
    rating: int | None = Field(default=None, ge=1, le=5)
    comments: str | None = Field(default=None, max_length=1000)
    confirm: bool | None = None


def build_workflow() -> PlannerWorkflowService:
    mode = os.getenv("PLANNER_LLM_MODE", "mock").strip().lower()
    if mode == "live":
        llm = OpenAIResponsesClient.from_env()
    elif mode == "mock":
        llm = DemoLLMClient()
    else:
        raise LLMError("PLANNER_LLM_MODE must be 'mock' or 'live'")

    vendor_service = VendorProcurementService.from_json_file(
        BACKEND_ROOT / "data" / "vendor_catalog.json"
    )
    supplier_portal = SupplierPortalService.from_env(vendor_service)
    quotation_service = MockVendorQuotationService.from_json_file(
        BACKEND_ROOT / "data" / "mock_vendor_quotations.json"
    )
    records = ProcurementRecordService.from_env()
    booking_service = VendorBookingService(
        MockVendorBookingService.from_json_file(
            BACKEND_ROOT / "data" / "mock_vendor_bookings.json"
        ),
        record_service=records,
    )
    procurement = VendorProcurementManagerAgent(
        llm,
        vendor_service,
        quotation_service,
        booking_service,
        record_service=records,
    )
    deposit_percent = int(os.getenv("DEPOSIT_PERCENT", "30"))
    timezone = os.getenv("APP_TIMEZONE", "Australia/Sydney")
    return PlannerWorkflowService(
        EventPlannerAgent(llm),
        procurement,
        FinancialManagerAgent(
            llm, FinancialWorkflowService(deposit_percent=deposit_percent)
        ),
        EventSessionService(),
        operations=EventOperationsAgent(
            llm,
            EventOperationsService(records.database_path, timezone=timezone),
        ),
        supplier_portal=supplier_portal,
        timezone=timezone,
        llm_mode=mode,
    )


workflow = build_workflow()
supplier_portal = workflow.supplier_portal
if supplier_portal is None:  # build_workflow always enables it for the HTTP API.
    raise RuntimeError("Supplier portal is not configured")
app = FastAPI(
    title="EventPilot API",
    version="0.1.0",
    description="Planning, procurement, financial and mock booking prototype API",
)
origins = [
    item.strip()
    for item in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "eventpilot-api",
        "llm_mode": os.getenv("PLANNER_LLM_MODE", "mock").strip().lower(),
    }


@app.post("/api/planner/message")
def planner_message(request: PlannerMessageRequest) -> dict:
    return workflow.handle_message(
        event_id=request.event_id,
        message=request.message.strip(),
    )


@app.get("/api/events/{event_id}")
def get_event(event_id: str) -> dict:
    event = workflow.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _run_event_action(action, event_id: str) -> dict:
    try:
        return action(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/{event_id}/quotations")
def request_quotations(event_id: str) -> dict:
    return _run_event_action(workflow.request_vendor_quotations, event_id)


@app.post("/api/events/{event_id}/plan-confirmation")
def confirm_plan(event_id: str) -> dict:
    return _run_event_action(workflow.confirm_plan, event_id)


@app.post("/api/events/{event_id}/quotation-selection")
def confirm_quotation_selection(
    event_id: str, request: QuotationSelectionRequest
) -> dict:
    try:
        return workflow.confirm_quotation_selection(event_id, request.quotation_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/{event_id}/quotation-approval")
def approve_quotation(event_id: str) -> dict:
    return _run_event_action(workflow.approve_customer_quotation, event_id)


@app.post("/api/events/{event_id}/deposit-payment")
def pay_deposit(event_id: str) -> dict:
    return _run_event_action(workflow.pay_deposit, event_id)


@app.post("/api/events/{event_id}/bookings")
def confirm_bookings(event_id: str) -> dict:
    return _run_event_action(workflow.confirm_bookings, event_id)


@app.get("/api/operations")
def list_operations() -> dict:
    try:
        return {"plans": workflow.list_operations()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/{event_id}/operations/{action}")
def update_operations(
    event_id: str, action: str, request: OperationsActionRequest
) -> dict:
    try:
        return workflow.perform_operations_action(
            event_id, action, request.model_dump(exclude_none=True)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vendors")
def list_vendors() -> dict:
    return {"vendors": supplier_portal.list_vendors()}


@app.get("/api/vendor/rfqs")
def list_vendor_quote_requests(vendor_id: str | None = None) -> dict:
    try:
        return {"requests": supplier_portal.list_quote_requests(vendor_id=vendor_id)}
    except (ValueError, SupplierPortalStorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vendor/rfqs/{request_id}/response")
def respond_to_vendor_quote_request(
    request_id: str, request: SupplierQuoteResponseRequest
) -> dict:
    try:
        return supplier_portal.respond_to_quote_request(
            request_id,
            available=request.available,
            quoted_total_cents=request.quoted_total_cents,
            message=request.message,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, SupplierPortalStorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vendor/confirmations")
def list_vendor_confirmations() -> dict:
    try:
        return {"confirmations": supplier_portal.list_confirmation_requests()}
    except (ValueError, SupplierPortalStorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vendor/confirmations/{confirmation_id}/response")
def respond_to_vendor_confirmation(
    confirmation_id: str, request: SupplierConfirmationResponseRequest
) -> dict:
    try:
        return supplier_portal.respond_to_confirmation(
            confirmation_id,
            confirmed=request.confirmed,
            message=request.message,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, SupplierPortalStorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vendor/reset")
def reset_vendor_cases() -> dict:
    try:
        supplier_cases = supplier_portal.clear_all_quote_requests()
        operations_cases = workflow.clear_operations()
        return {
            "cleared_cases": supplier_cases + operations_cases,
            "cleared_supplier_cases": supplier_cases,
            "cleared_operations_cases": operations_cases,
        }
    except (SupplierPortalStorageError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
