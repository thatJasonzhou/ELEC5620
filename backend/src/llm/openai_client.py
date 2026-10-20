"""OpenAI Responses API transport.

All credentials and model choices come from environment variables. The client
never logs request bodies, credentials, or provider responses.
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .base import LLMClient, LLMError


class OpenAIResponsesClient(LLMClient):
    """Synchronous OpenAI client with optional Structured Outputs."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 30) -> None:
        if not api_key.strip():
            raise LLMError("OPENAI_API_KEY is required in live mode")
        if not model.strip():
            raise LLMError("OPENAI_MODEL is required in live mode")
        self._model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)

    @classmethod
    def from_env(cls) -> "OpenAIResponsesClient":
        try:
            timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise LLMError("OPENAI_TIMEOUT_SECONDS must be numeric") from exc
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout_seconds=timeout,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            response = self._client.responses.create(
                model=self._model,
                input=messages,
            )
        except Exception as exc:  # provider exceptions vary by SDK version
            raise LLMError(f"OpenAI request failed: {type(exc).__name__}") from exc
        text = response.output_text
        if not isinstance(text, str) or not text.strip():
            raise LLMError("OpenAI returned no text output")
        return text

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        try:
            response = self._client.responses.create(
                model=self._model,
                input=messages,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        except Exception as exc:
            raise LLMError(f"OpenAI structured request failed: {type(exc).__name__}") from exc
        try:
            parsed = json.loads(response.output_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMError("OpenAI returned invalid structured output") from exc
        if not isinstance(parsed, dict):
            raise LLMError("OpenAI structured output must be an object")
        return parsed
