"""Centralized LLM access (KAN-16).

All Agent modules must call the LLM through this package (AGENTS.md
section 6). Public names:

- :class:`LLMClient` — abstract interface, ``complete(messages) -> str``
- :class:`LLMError`   — transport/config/parse failures (no secrets)
- :class:`CampusQwenClient` — real client for the Campus Qwen proxy
- :class:`MockLLMClient`    — clearly-marked mock for tests/demos
"""
from .base import LLMClient, LLMError
from .campus_qwen import CampusQwenClient
from .mock import MockLLMClient

__all__ = [
    "CampusQwenClient",
    "LLMClient",
    "LLMError",
    "MockLLMClient",
]
