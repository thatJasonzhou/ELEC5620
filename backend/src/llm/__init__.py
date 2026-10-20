"""Centralized LLM access for all business Agents.

All Agent modules must call the LLM through this package (AGENTS.md
section 6). Public names:

- :class:`LLMClient` — abstract interface, ``complete(messages) -> str``
- :class:`LLMError`   — transport/config/parse failures (no secrets)
- :class:`OpenAIResponsesClient` — live OpenAI Responses API client
- :class:`DemoLLMClient` — local deterministic end-to-end demo client
- :class:`MockLLMClient`    — clearly-marked mock for tests/demos
"""
from .base import LLMClient, LLMError
from .demo import DemoLLMClient
from .mock import MockLLMClient
from .openai_client import OpenAIResponsesClient

__all__ = [
    "DemoLLMClient",
    "LLMClient",
    "LLMError",
    "MockLLMClient",
    "OpenAIResponsesClient",
]
