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
