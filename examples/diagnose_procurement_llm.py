"""Probe a real shortlist request; print metadata instead of server/model text."""
from __future__ import annotations

import argparse
import json
from time import monotonic
import urllib.error

from examples.shared_catalog_procurement_example import build_agent, event_request
from src.llm import CampusQwenClient, LLMError


def response_metadata(raw):
    """Allowlist structural diagnostics; never echo server-controlled strings."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"envelope": "invalid_json"}
    try:
        choice = data["choices"][0]
        message = choice["message"]
        if not isinstance(choice, dict) or not isinstance(message, dict):
            return {"envelope": "invalid_choice"}
    except (TypeError, KeyError, IndexError):
        return {"envelope": "invalid_choice"}
    content = message.get("content")
    result = {"envelope": "valid_json"}
    if "content" not in message:
        result["envelope"] = "missing_content"
    elif not isinstance(content, str):
        result["envelope"] = "non_string_content"
    elif not content.strip():
        result["envelope"] = "empty_content"
    if isinstance(content, str):
        result["content_chars"] = len(content)
    finish = choice.get("finish_reason")
    result["finish"] = finish if isinstance(finish, str) and finish in {
        "stop", "length", "tool_calls", "content_filter", "function_call"
    } else "unknown"
    for key in ("reasoning_content", "reasoning"):
        if isinstance(message.get(key), str):
            result[key + "_chars"] = len(message[key])
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if type(usage.get(key)) is int and usage[key] >= 0:
                result[key] = usage[key]
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and type(details.get("reasoning_tokens")) is int and details["reasoning_tokens"] >= 0:
            result["reasoning_tokens"] = details["reasoning_tokens"]
    return result


class DiagnosticCampusClient(CampusQwenClient):
    """Retain production retries; reveal each underlying HTTP attempt."""

    def _open_and_read(self, request):
        self.attempt_count = getattr(self, "attempt_count", 0) + 1
        attempt = self.attempt_count
        start = monotonic()
        print(f"Attempt {attempt}: started", flush=True)
        try:
            raw = super()._open_and_read(request)
        except urllib.error.HTTPError as exc:
            status = exc.code if type(exc.code) is int and 400 <= exc.code <= 599 else "unknown"
            print(f"Attempt {attempt}: HTTP {status} | elapsed={monotonic() - start:.2f}s", flush=True)
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            print(f"Attempt {attempt}: network_or_timeout | elapsed={monotonic() - start:.2f}s", flush=True)
            raise
        except UnicodeDecodeError:
            print(f"Attempt {attempt}: invalid_utf8 | elapsed={monotonic() - start:.2f}s", flush=True)
            raise
        self.last_metadata = response_metadata(raw)
        fields = " | ".join(f"{key}={value}" for key, value in self.last_metadata.items())
        print(f"Attempt {attempt}: HTTP success | elapsed={monotonic() - start:.2f}s | {fields}", flush=True)
        return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-output-tokens", type=int, default=256,
                        help="Output cap for this single probe; 0 uses the server default.")
    parser.add_argument("--baseline", action="store_true", help="Probe Reply OK instead of the actual shortlist prompt.")
    parser.add_argument('--disable-thinking', action='store_true',
                        help='Request Qwen non-thinking mode; backend support must be verified.')
    parser.add_argument('--no-think-prompt', action='store_true',
                        help='Append Qwen /no_think to the prompt without sending an API extension.')
    args = parser.parse_args()
    if args.no_think_prompt and args.disable_thinking:
        parser.error('Choose only one thinking control.')
    if args.max_output_tokens < 0:
        parser.error("--max-output-tokens must be nonnegative.")
    if args.baseline:
        messages = [{"role": "user", "content": "Reply with exactly OK."}]
    else:
        # Build the real prompt offline; no Live supplier request or booking.
        agent = build_agent()
        prepared = agent.prepare_event_enquiries(event_request(services=["photography"]))
        if prepared["status"] != "success":
            raise RuntimeError("Offline shortlist fixture could not be prepared")
        messages = agent.llm.calls[0]
    if args.no_think_prompt:
        messages = [dict(message) for message in messages]
        messages[-1]['content'] += '\n/no_think'
    chars = sum(len(message['content']) for message in messages)
    print(f"Probe: {'baseline' if args.baseline else 'photography shortlist'} | input_chars={chars} | max_tokens={args.max_output_tokens or 'server_default'}", flush=True)
    start = monotonic()
    thinking = 'prompt_no_think_requested' if args.no_think_prompt else (
        'disabled_requested' if args.disable_thinking else 'server_default')
    print(f'Thinking: {thinking}', flush=True)
    client = None
    try:
        client = DiagnosticCampusClient.from_env(max_output_tokens=args.max_output_tokens or None,
                                                  enable_thinking=False if args.disable_thinking else None)
        client.complete(messages)
    except LLMError as exc:
        metadata = getattr(client, "last_metadata", {})
        reason = "output_limit" if metadata.get("finish") == "length" else metadata.get("envelope", "unavailable")
        print(f"Result: error | code={exc.code} | detail={reason} | elapsed={monotonic() - start:.2f}s")
        raise SystemExit(1)
    print(f"Result: response_received | elapsed={monotonic() - start:.2f}s | ranking_not_validated")


if __name__ == "__main__":
    main()
