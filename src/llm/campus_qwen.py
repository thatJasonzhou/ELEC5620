"""Campus Qwen API Proxy client via stdlib ``urllib`` (KAN-16).

Transport-level concerns (endpoint, auth, parameters, timeout, one
retry on transient network faults) are centralized here. The real
endpoint URL format, model name and auth scheme have NOT been confirmed
with the school yet, so:

- ``ELEC5620_LLM_BASE_URL`` is treated as the *full* chat-completions
  endpoint URL (no path is appended);
- the model name must be provided via ``ELEC5620_LLM_MODEL``;
- the auth header assumes ``Authorization: Bearer <key>`` (assumption
  pending confirmation);
- the response is assumed to be OpenAI-style JSON, with the reply in
  ``choices[0].message.content`` (assumption pending confirmation).

Missing configuration fails with a clear :class:`LLMError` that lists
the missing variable names — never the values — instead of guessing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import LLMClient, LLMError

_ENV_BASE_URL = "ELEC5620_LLM_BASE_URL"
_ENV_API_KEY = "ELEC5620_LLM_API_KEY"
_ENV_MODEL = "ELEC5620_LLM_MODEL"

# HTTP status codes considered transient (retried once).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CampusQwenClient(LLMClient):
    """Synchronous chat-completions client for the Campus Qwen proxy."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise LLMError("base_url must be a non-empty string")
        if not isinstance(api_key, str) or not api_key:
            raise LLMError("api_key must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise LLMError("model must be a non-empty string")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise LLMError("timeout_seconds must be a positive number")
        self._base_url = base_url.strip()
        self._api_key = api_key
        self._model = model.strip()
        self._timeout = float(timeout_seconds)

    @classmethod
    def from_env(cls) -> "CampusQwenClient":
        """Build a client from environment variables.

        Only the three ELEC5620_LLM_* variables are read at runtime.
        Missing variables are named in the error; their values are
        never echoed.
        """
        missing = [
            name
            for name in (_ENV_BASE_URL, _ENV_API_KEY, _ENV_MODEL)
            if not os.environ.get(name)
        ]
        if missing:
            raise LLMError(
                "LLM configuration is missing environment variables: "
                + ", ".join(missing)
                + ". Set them in the environment before running."
            )
        return cls(
            base_url=os.environ[_ENV_BASE_URL],
            api_key=os.environ[_ENV_API_KEY],
            model=os.environ[_ENV_MODEL],
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                # Assumed auth scheme pending confirmation.
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_STATUS:
                return self._send_once(request)
            if exc.code in (401, 403):
                raise LLMError(
                    f"LLM authentication failed (HTTP {exc.code}); "
                    "check the API key and endpoint configuration."
                ) from None
            raise LLMError(
                f"LLM request failed with HTTP {exc.code}: "
                f"{exc.reason or 'no reason given'}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Transient network fault: retry once.
            return self._retry_after_network_fault(request, exc)
        return self._parse_response(raw)

    def _send_once(self, request: urllib.request.Request) -> str:
        """Second attempt after a retryable HTTP status (no further retry)."""
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LLMError(
                f"LLM request failed with HTTP {exc.code} on retry: "
                f"{exc.reason or 'no reason given'}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(
                f"LLM request still failing on retry: {exc}"
            ) from None
        return self._parse_response(raw)

    def _retry_after_network_fault(
        self,
        request: urllib.request.Request,
        first_error: Exception,
    ) -> str:
        del first_error  # kept for clarity; message is generic on purpose
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LLMError(
                f"LLM request failed with HTTP {exc.code} on retry after "
                "network fault."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"LLM request failed after retry: {exc}") from None
        return self._parse_response(raw)

    @staticmethod
    def _parse_response(raw: str) -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise LLMError("LLM response is not valid JSON") from None
        try:
            content = data["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise LLMError(
                "LLM response is missing choices[0].message.content"
            ) from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM response content is empty or not a string")
        return content
