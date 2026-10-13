from app.models.enums import EventStatus


class InvalidTransitionError(ValueError):
    pass


class WorkflowService:
    _allowed_transitions: dict[EventStatus, set[EventStatus]] = {
        EventStatus.DRAFT: {EventStatus.REQUIREMENTS_DEFINED, EventStatus.CANCELLED},
        EventStatus.REQUIREMENTS_DEFINED: {EventStatus.PROPOSAL_GENERATED, EventStatus.CANCELLED},
        EventStatus.PROPOSAL_GENERATED: {EventStatus.PROPOSAL_APPROVED, EventStatus.CANCELLED},
        EventStatus.PROPOSAL_APPROVED: {EventStatus.BOOKING_CONFIRMED, EventStatus.CANCELLED},
        EventStatus.BOOKING_CONFIRMED: {EventStatus.PREPARING, EventStatus.CANCELLED},
        EventStatus.PREPARING: {EventStatus.IN_PROGRESS, EventStatus.CANCELLED},
        EventStatus.IN_PROGRESS: {EventStatus.COMPLETED, EventStatus.CANCELLED},
        EventStatus.COMPLETED: {EventStatus.CLOSED},
        EventStatus.CLOSED: set(),
        EventStatus.CANCELLED: set(),
    }

    def validate_transition(self, current: EventStatus, target: EventStatus) -> None:
        if target not in self._allowed_transitions[current]:
            raise InvalidTransitionError(f"Cannot move event from {current} to {target}.")

