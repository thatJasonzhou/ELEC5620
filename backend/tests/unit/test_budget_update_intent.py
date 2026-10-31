import pytest

from src.services.planner_workflow_service import PlannerWorkflowService


@pytest.mark.parametrize(
    "message",
    [
        "Please add photography from 9 am to 5 pm. Keep everything else unchanged.",
        "Please add photography from 09:00 to 17:00.",
        "Add 2 event staff.",
        "Increase the guest count to 80.",
        "Move lighting to 10 am and keep the budget unchanged.",
        "Add photography at 9 am, with no change to my budget.",
    ],
)
def test_non_financial_numbers_do_not_change_budget(message: str) -> None:
    assert PlannerWorkflowService._extract_budget_update(
        message, current_budget_cents=1_000_000, required_total_cents=1_200_000
    ) is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Please change my total budget to AUD 8000.", 800_000),
        ("Increase my budget to 8000 AUD.", 800_000),
        ("Increase my budget by 1000 AUD.", 1_100_000),
        ("Add AUD 1000 to my budget.", 1_100_000),
        ("Increase it by $1000.", 1_100_000),
        ("My budget is 8k.", 800_000),
        ("At 9 am, change my budget to 8000.", 800_000),
        ("At 9 am, increase my budget by AUD 1000.", 1_100_000),
        ("增加7072成本", 1_707_200),
    ],
)
def test_explicit_money_changes_remain_supported(message: str, expected: int) -> None:
    assert PlannerWorkflowService._extract_budget_update(
        message, current_budget_cents=1_000_000, required_total_cents=None
    ) == expected
