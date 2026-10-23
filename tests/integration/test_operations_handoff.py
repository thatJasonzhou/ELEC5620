from examples.operations_example import run_demo, build_demo_request
from src.agents.event_operations import EventOperationsAgent
from src.llm import MockLLMClient
from src.services.event_operations_service import InMemoryEventOperationsService


def test_actual_procurement_financial_to_operations():
    result = run_demo()
    assert result["data"]["summary"]["execution_complete"]
    assert result["data"]["summary"]["completed"] == 2


def test_partial_confirmations_never_advance():
    request = build_demo_request()
    # Even retained confirmed bookings cannot hide a failed overall booking run.
    request["procurement_result"]["status"] = "blocked"
    agent = EventOperationsAgent(MockLLMClient(), InMemoryEventOperationsService())
    assert agent.handle(request)["status"] == "blocked"
