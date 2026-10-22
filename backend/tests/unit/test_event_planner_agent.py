import json

from src.agents.event_planner import EventPlannerAgent
from src.llm import MockLLMClient


def test_planner_merges_updates_and_asks_for_next_missing_group() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "I recorded the wedding details.",
                "updates": {
                    "event_type": "Wedding",
                    "event_date": None,
                    "start_time": None,
                    "end_time": None,
                    "location": "Sydney",
                    "guest_count": 80,
                    "budget_limit_cents": None,
                    "required_services": None,
                    "customer_preferences": None,
                },
                "decision_summary": ["Detected wedding", "Detected Sydney"],
            }
        )
    )
    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-1",
            "message": "Wedding in Sydney for 80 guests",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "needs_input"
    assert result["data"]["progress"]["completed"] == 3
    assert result["data"]["progress"]["missing_fields"][0] == "date_time"
    assert "exact event date" in result["message"]


def test_planner_rejects_invalid_model_date() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Done.",
                "updates": {
                    "event_type": None,
                    "event_date": "not-a-date",
                    "start_time": None,
                    "end_time": None,
                    "location": None,
                    "guest_count": None,
                    "budget_limit_cents": None,
                    "required_services": None,
                    "customer_preferences": None,
                },
                "decision_summary": ["Date supplied"],
            }
        )
    )
    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-1",
            "message": "some date",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "error"
    assert "YYYY-MM-DD" in result["message"]


def test_planner_accepts_empty_customer_preferences() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "The requirements are complete.",
                "updates": {
                    "event_type": "Wedding",
                    "event_date": "2026-12-05",
                    "start_time": "15:00",
                    "end_time": "21:00",
                    "location": "Sydney",
                    "guest_count": 80,
                    "budget_limit_cents": 3_000_000,
                    "required_services": ["catering", "photography"],
                    "customer_preferences": "",
                },
                "decision_summary": ["All required details supplied"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-1",
            "message": "Wedding details",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "success"
    assert result["data"]["requirements"]["customer_preferences"] == ""


def test_planner_asks_once_when_services_have_not_been_discussed() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "I recorded the event details.",
                "updates": {
                    "event_type": "Birthday party",
                    "event_date": "2026-12-05",
                    "start_time": "15:00",
                    "end_time": "18:00",
                    "location": "Sydney",
                    "guest_count": 30,
                    "budget_limit_cents": 500_000,
                    "required_services": None,
                    "services_confirmed": None,
                    "vendor_budget_cents": 350_000,
                    "customer_preferences": None,
                },
                "decision_summary": ["Recorded the core event details"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-2",
            "message": "Birthday details",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "needs_input"
    assert result["data"]["progress"]["completed"] == 5
    assert result["data"]["progress"]["missing_fields"] == ["services"]
    assert "additional services" in result["message"]


def test_planner_accepts_confirmed_empty_service_preference() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "No extra services are needed.",
                "updates": {
                    "event_type": None,
                    "event_date": None,
                    "start_time": None,
                    "end_time": None,
                    "location": None,
                    "guest_count": None,
                    "budget_limit_cents": None,
                    "required_services": [],
                    "services_confirmed": True,
                    "vendor_budget_cents": None,
                    "customer_preferences": None,
                },
                "decision_summary": ["No additional services requested"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-3",
            "message": "I do not need any extra services.",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {
                "event_type": "Birthday party",
                "event_date": "2026-12-05",
                "start_time": "15:00",
                "end_time": "18:00",
                "location": "Sydney",
                "guest_count": 30,
                "budget_limit_cents": 500_000,
                "vendor_budget_cents": 350_000,
                "required_services": [],
                "services_confirmed": False,
            },
            "history": [],
        }
    )

    assert result["status"] == "success"
    assert result["data"]["requirements"]["required_services"] == []
    assert result["data"]["requirements"]["services_confirmed"] is True


def test_planner_rejects_vendor_budget_above_total_budget() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Budget allocated.",
                "updates": {
                    "budget_limit_cents": 500_000,
                    "vendor_budget_cents": 600_000,
                },
                "decision_summary": ["Allocated vendor budget"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-4",
            "message": "My budget is 5000 dollars.",
            "current_date": "2026-10-20",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "error"
    assert "must not exceed" in result["message"]
