from src.api.app import (
    PlannerMessageRequest,
    VendorSelectionRequest,
    health,
    planner_message,
)


def test_health() -> None:
    response = health()
    assert response["status"] == "ok"


def test_planner_message_contract() -> None:
    body = planner_message(
        PlannerMessageRequest(message="I need a wedding in Sydney for 80 guests.")
    )
    assert body["event_id"].startswith("EV-")
    assert body["requirements"]["event_type"] == "Wedding"
    assert body["progress"]["completed"] == 3


def test_vendor_selection_contract_accepts_one_vendor_per_service() -> None:
    body = VendorSelectionRequest(
        offering_ids=["V-CAT-001-O2", "V-PHOTO-001-O2"]
    )
    assert body.offering_ids == ["V-CAT-001-O2", "V-PHOTO-001-O2"]
