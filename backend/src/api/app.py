"""HTTP API connecting the React interface to Planning and Procurement."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agents import EventPlannerAgent, VendorProcurementManagerAgent
from src.llm import DemoLLMClient, LLMError, OpenAIResponsesClient
from src.services.event_session_service import EventSessionService
from src.services.planner_workflow_service import PlannerWorkflowService
from src.services.vendor_procurement_service import VendorProcurementService


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT.parent / ".env")


class PlannerMessageRequest(BaseModel):
    event_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class VendorSelectionRequest(BaseModel):
    offering_ids: list[str] = Field(min_length=1)


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
    return PlannerWorkflowService(
        EventPlannerAgent(llm),
        VendorProcurementManagerAgent(llm, vendor_service),
        EventSessionService(),
        timezone=os.getenv("APP_TIMEZONE", "Australia/Sydney"),
        llm_mode=mode,
    )


workflow = build_workflow()
app = FastAPI(
    title="EventPilot API",
    version="0.1.0",
    description="Event Planner and Vendor Procurement prototype API",
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


@app.post("/api/events/{event_id}/vendor-selection")
def confirm_vendor_selection(event_id: str, request: VendorSelectionRequest) -> dict:
    try:
        return workflow.confirm_vendor_selection(event_id, request.offering_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
