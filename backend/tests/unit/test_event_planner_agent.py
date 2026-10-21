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
