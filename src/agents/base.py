"""Abstract base class for business Agents (KAN-16).

Per the Stage 1 UML all business Agents inherit ``AIAgent`` and are
called with a structured request dict, returning a structured response
envelope (shared-data-and-interfaces.md, section 5).

This is a minimal, prototype-level base class:

- it defines the request/response contract only;
- it holds the LLM client (the one shared dependency);
- it does NOT introduce persistence, a dependency container, or
  Stage-1 business methods — those stay in the concrete Agents and the
  Service layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar

from src.llm import LLMClient

#: Envelope statuses per shared-data-and-interfaces.md.
VALID_STATUSES = ("success", "needs_input", "blocked", "error")


class AIAgent(ABC):
    """Base class for the four business Agents."""

    #: Stable identifier used in the envelope ``agent`` field
    #: (planning / procurement / finance / operations).
    agent_name: ClassVar[str]

    def __init__(self, llm: LLMClient) -> None:
        if not isinstance(llm, LLMClient):
            raise TypeError("llm must be an LLMClient instance")
        self.llm = llm

    @abstractmethod
    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process one structured request and return the envelope."""

    # ------------------------------------------------------------------
    # Envelope helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _now() -> str:
        """ISO 8601 timestamp with UTC offset, seconds precision."""
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def envelope(
        self,
        event_id: str | None,
        status: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the standard response envelope.

        ``event_id`` is ``None`` when the request did not carry a valid
        event id (e.g. it was missing or not a string).
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {VALID_STATUSES}, got {status!r}"
            )
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        return {
            "event_id": event_id,
            "agent": self.agent_name,
            "timestamp": self._now(),
            "status": status,
            "message": message,
            "data": data if data is not None else {},
        }
