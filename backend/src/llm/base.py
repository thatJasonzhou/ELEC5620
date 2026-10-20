"""Abstract LLM client interface for all Agent modules (KAN-16).

Per AGENTS.md, every LLM call must go through this package: prompt
construction stays with the calling module, while transport, parameters,
retries and failure handling live here.

The client contract is minimal on purpose: ``complete(messages) -> str``.
The caller is responsible for parsing and validating whatever text the
model returns.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any


class LLMError(Exception):
    """Raised when an LLM call cannot be completed.

    Messages must never contain API keys or other secrets.
    """


class LLMClient(ABC):
    """Minimal synchronous chat-completion interface."""

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Send chat messages and return the model's text response.

        ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts
        (roles: ``system``, ``user``). Raises :class:`LLMError` on
        transport failure, malformed responses, or invalid configuration.
        """

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        """Return a JSON object validated by the calling Agent.

        Simple/mock clients use their normal text completion. A live client may
        override this method to request provider-side structured output.
        """
        del schema, schema_name
        try:
            parsed = json.loads(self.complete(messages))
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM response is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError("LLM structured response must be a JSON object")
        return parsed
