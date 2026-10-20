"""Mock LLM client for tests and local demos (KAN-16).

This is a clearly-marked MOCK, not a real model. It returns scripted
responses in order (or from a callable) and records every call so tests
can assert, for example, that no LLM call was made when a request is
blocked before reaching the model.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import LLMClient, LLMError


class MockLLMClient(LLMClient):
    """Scripted stand-in for :class:`LLMClient`.

    ``responses`` may be:
    - a string, returned for every call; or
    - a list of strings / exceptions, returned one per call in order
      (an exception item is raised instead of returned); or
    - a callable ``fn(messages) -> str``.

    When a list is exhausted, a :class:`LLMError` is raised so that
    unexpected calls fail loudly instead of returning nothing.

    Runtime reconfiguration:
    - :meth:`set_response` — return ``text`` for all subsequent calls;
    - :meth:`set_exception` — raise ``exc`` for all subsequent calls.
    """

    def __init__(self, responses: Any = "") -> None:
        self._responses: Callable[[list[dict[str, str]]], str] | None
        self._queue: list[str | Exception] | None = None
        self._static: str | None = None
        if callable(responses):
            self._responses = responses
        elif isinstance(responses, list):
            self._responses = None
            self._queue = list(responses)
        elif isinstance(responses, str):
            self._responses = None
            self._static = responses
        else:
            raise LLMError(
                "MockLLMClient responses must be a string, a list of "
                "strings/exceptions, or a callable, got "
                f"{type(responses).__name__}"
            )
        for item in self._queue or []:
            if not isinstance(item, (str, Exception)):
                raise LLMError(
                    "MockLLMClient responses list items must be strings "
                    f"or exceptions, got {type(item).__name__}"
                )
        self.calls: list[list[dict[str, str]]] = []
        self._exception: Exception | None = None

    def set_response(self, text: str) -> None:
        """Return ``text`` for all subsequent calls."""
        if not isinstance(text, str):
            raise LLMError("set_response expects a string")
        self._responses = None
        self._queue = None
        self._exception = None
        self._static = text

    def set_exception(self, exc: Exception) -> None:
        """Raise ``exc`` for all subsequent calls."""
        if not isinstance(exc, Exception):
            raise LLMError("set_exception expects an Exception instance")
        self._responses = None
        self._queue = None
        self._exception = exc
        self._static = None

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        if self._exception is not None:
            raise self._exception
        if self._responses is not None:
            return self._responses(messages)
        if self._queue is not None:
            if not self._queue:
                raise LLMError("MockLLMClient: scripted responses exhausted")
            item = self._queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._static is not None:
            return self._static
        raise LLMError("MockLLMClient: no responses configured")
