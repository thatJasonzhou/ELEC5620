import pytest

from app.models.enums import EventStatus
from app.services.workflow_service import InvalidTransitionError, WorkflowService


def test_allows_expected_event_transition() -> None:
    WorkflowService().validate_transition(
        EventStatus.PROPOSAL_APPROVED,
        EventStatus.BOOKING_CONFIRMED,
    )


def test_rejects_skipped_event_transition() -> None:
    with pytest.raises(InvalidTransitionError):
        WorkflowService().validate_transition(EventStatus.DRAFT, EventStatus.CLOSED)

