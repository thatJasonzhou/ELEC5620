import json

from src.agents.event_planner import EventPlannerAgent
from src.llm import MockLLMClient


def test_plan_services_drops_stale_removed_service_from_model_output() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Photography has been removed from the plan.",
                "decision_summary": ["Removed photography"],
                "service_schedule": [
                    {
                        "service_type": "venue",
                        "arrival_time": "12:00",
                        "start_time": "15:00",
                        "end_time": "18:00",
                        "notes": "Venue setup",
                    },
                    {
                        "service_type": "photography",
                        "arrival_time": "14:30",
                        "start_time": "15:00",
                        "end_time": "18:00",
                        "notes": "Stale previous-plan entry",
                    },
                ],
            }
        )
    )
    result = EventPlannerAgent(llm).plan_services(
        {
            "event_id": "EV-REMOVE-SERVICE",
            "requirements": {
                "event_date": "2026-12-05",
                "start_time": "15:00",
                "end_time": "18:00",
                "required_services": ["venue"],
            },
            "current_schedule": [
                {"service_type": "venue"},
                {"service_type": "photography"},
            ],
            "message": "No need for photography.",
        }
    )

    assert result["status"] == "success"
    assert [
        item["service_type"] for item in result["data"]["service_schedule"]
    ] == ["venue"]


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
    assert "Do you need any services" in result["message"]


def test_planner_recovers_explicit_services_omitted_by_model() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Saved.",
                "updates": {
                    "event_type": "Conference",
                    "event_date": "2026-12-16",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "location": "Sydney",
                    "guest_count": 50,
                    "budget_limit_cents": 10_000_000,
                    "required_services": None,
                    "services_confirmed": None,
                    "customer_preferences": None,
                },
                "decision_summary": ["Recorded event details"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-SERVICES",
            "message": "I need lighting and event staff.",
            "current_date": "2026-10-28",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    assert result["status"] == "success"
    assert result["data"]["requirements"]["required_services"] == [
        "venue",
        "lighting",
        "event_staff",
    ]


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
    assert result["data"]["requirements"]["required_services"] == ["venue"]
    assert result["data"]["requirements"]["services_confirmed"] is True


def test_planner_ignores_obsolete_vendor_budget_output() -> None:
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

    assert result["status"] == "needs_input"
    assert result["data"]["requirements"]["budget_limit_cents"] == 500_000
    assert "vendor_budget_cents" not in result["data"]["requirements"]


def test_planner_corrects_dollars_returned_as_cents_by_model() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Budget updated.",
                "updates": {
                    "budget_limit_cents": 30_000,
                    "vendor_budget_cents": 21_000,
                },
                "decision_summary": ["Updated the budget"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-5",
            "message": "Change my budget to $30000.",
            "current_date": "2026-10-24",
            "timezone": "Australia/Sydney",
            "saved_requirements": {},
            "history": [],
        }
    )

    requirements = result["data"]["requirements"]
    assert requirements["budget_limit_cents"] == 3_000_000
    assert "vendor_budget_cents" not in requirements


def test_planner_drops_saved_vendor_budget_when_total_budget_changes() -> None:
    llm = MockLLMClient(
        json.dumps(
            {
                "reply": "Budget updated.",
                "updates": {
                    "budget_limit_cents": 30_000,
                    "vendor_budget_cents": None,
                },
                "decision_summary": ["Updated the budget"],
            }
        )
    )

    result = EventPlannerAgent(llm).handle(
        {
            "event_id": "EV-6",
            "message": "Change my budget to 30,000 AUD.",
            "current_date": "2026-10-24",
            "timezone": "Australia/Sydney",
            "saved_requirements": {
                "budget_limit_cents": 50_000,
                "vendor_budget_cents": 35_000,
            },
            "history": [],
        }
    )

    requirements = result["data"]["requirements"]
    assert requirements["budget_limit_cents"] == 3_000_000
    assert "vendor_budget_cents" not in requirements
