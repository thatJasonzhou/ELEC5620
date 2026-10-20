from src.api.app import PlannerMessageRequest, health, planner_message


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
