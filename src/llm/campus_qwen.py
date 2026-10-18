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

Configuration errors fail with a clear :class:`LLMError` that names
what is wrong but never includes the configured value (a URL or key
may itself be sensitive). Missing configuration from
:meth:`CampusQwenClient.from_env` lists the missing variable names —
never their values.

Runtime failures map to :class:`LLMError` as follows:

- transient faults (retryable HTTP status, network/timeout errors)
  trigger exactly one retry; any failure after the retry, or a
  non-retryable HTTP status, becomes an :class:`LLMError`;
- request construction and response read/decode failures (invalid
  URL parse, non-UTF-8 body, unexpected transport errors) become an
  :class:`LLMError` immediately, with no retry.

The failure classes are caught deliberately and narrowly; unexpected
programming errors (e.g. ``AttributeError``, ``TypeError``) are NOT
masked by broad catches.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
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
        self._base_url = self._validate_base_url(base_url)
        if not isinstance(api_key, str) or not api_key:
            raise LLMError("api_key must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise LLMError("model must be a non-empty string")
        self._api_key = api_key
        self._model = model.strip()
        self._timeout = self._validate_timeout(timeout_seconds)

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
        body = json.dumps(
            {"model": self._model, "messages": messages}
        ).encode("utf-8")
        try:
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
        except ValueError:
            raise LLMError(
                "LLM request could not be constructed: invalid "
                "endpoint URL."
            ) from None
        raw = self._send_with_retry(request)
        return self._parse_response(raw)

    def _send_with_retry(self, request: urllib.request.Request) -> str:
        """First attempt; on a transient fault, exactly one retry."""
        try:
            return self._open_and_read(request)
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
        except UnicodeDecodeError:
            raise LLMError("LLM response is not valid UTF-8") from None
        except ValueError:
            # Invalid URL during send — impossible after __init__
            # validation, kept as a safety net.
            raise LLMError(
                "LLM request could not be sent: invalid endpoint URL."
            ) from None

    def _send_once(self, request: urllib.request.Request) -> str:
        """Second attempt after a retryable HTTP status (no further retry)."""
        try:
            return self._open_and_read(request)
        except urllib.error.HTTPError as exc:
            raise LLMError(
                f"LLM request failed with HTTP {exc.code} on retry: "
                f"{exc.reason or 'no reason given'}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(
                "LLM request still failing on retry (network fault)."
            ) from None
        except UnicodeDecodeError:
            raise LLMError(
                "LLM response is not valid UTF-8 (on retry)."
            ) from None
        except ValueError:
            raise LLMError(
                "LLM request could not be sent on retry: invalid "
                "endpoint URL."
            ) from None

    def _retry_after_network_fault(
        self,
        request: urllib.request.Request,
        first_error: Exception,
    ) -> str:
        del first_error  # kept for clarity; message is generic on purpose
        try:
            return self._open_and_read(request)
        except urllib.error.HTTPError as exc:
            raise LLMError(
                f"LLM request failed with HTTP {exc.code} on retry "
                "after network fault."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            # Generic message on purpose: raw exception text (e.g. a
            # URLError's repr) can embed the endpoint URL, which may
            # itself carry credentials.
            raise LLMError(
                "LLM request failed after retry (network fault)."
            ) from None
        except UnicodeDecodeError:
            raise LLMError(
                "LLM response is not valid UTF-8 (after retry)."
            ) from None
        except ValueError:
            raise LLMError(
                "LLM request could not be sent after retry: invalid "
                "endpoint URL."
            ) from None

    def _open_and_read(self, request: urllib.request.Request) -> str:
        """Open the request and return the response body as UTF-8 text.

        Raises:

        - ``urllib.error.HTTPError`` — non-2xx HTTP response;
        - ``(urllib.error.URLError, TimeoutError, OSError)`` — network
          fault;
        - ``ValueError`` — invalid URL during send (should be impossible
          after ``__init__`` validation, kept as a safety net);
        - ``UnicodeDecodeError`` — response body is not valid UTF-8.

        Those are the *expected* transport failures; callers convert
        them to :class:`LLMError` so the Agent can return an error
        envelope. No broader exceptions are caught here.
        """
        with urllib.request.urlopen(
            request, timeout=self._timeout
        ) as resp:
            return resp.read().decode("utf-8")

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

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        """Validate that ``base_url`` is an http(s) URL with a host.

        Error messages deliberately omit the value: a URL may embed
        credentials in its authority component.
        """
        if not isinstance(base_url, str) or not base_url.strip():
            raise LLMError("base_url must be a non-empty string")
        try:
            parts = urllib.parse.urlsplit(base_url)
        except ValueError:
            raise LLMError("base_url is not a valid URL") from None
        if parts.scheme not in ("http", "https"):
            raise LLMError(
                "base_url must use the http or https scheme"
            )
        if not parts.hostname:
            raise LLMError(
                "base_url must include a host (e.g. http://host[:port])"
            )
        return base_url.strip()

    @staticmethod
    def _validate_timeout(timeout_seconds: float) -> float:
        """Require a finite positive number (bool/NaN/Infinity rejected)."""
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise LLMError("timeout_seconds must be a finite positive number")
        return float(timeout_seconds)
