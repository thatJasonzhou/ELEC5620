"""Bounded independent LLM calls; no enquiry, database or booking state enters workers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from .base import LLMClient, LLMError


@dataclass(frozen=True)
class Completion:
    text: str | None
    failed: bool
    elapsed_seconds: float
    error_code: str | None = None
    http_status: int | None = None
    retryable: bool = False
    attempts: int = 1


def complete_jobs(
    llm: LLMClient,
    jobs: list[tuple[str, list[dict[str, str]]]],
    *,
    max_workers: int = 1,
    stage: str,
    retry_failed: bool = False,
    progress: Callable[[dict], None] | None = None,
) -> list[Completion]:
    """Keep result order; callbacks run on the caller thread, never pool threads.

    A submitted event includes queued work. A success event means a response was
    received, not that business validation or selection has succeeded.
    Only expected LLMError failures are converted; programming errors propagate.
    Concurrent mode requires a client whose complete() supports concurrent calls.
    """
    if type(max_workers) is not int or not 1 <= max_workers <= 5:
        raise ValueError("max_workers must be an integer from 1 to 5")
    if not jobs:
        return []

    def notify(index, state, result=None):
        if progress is not None:
            event = {"stage": stage, "service_type": jobs[index][0], "state": state}
            if result is not None:
                event["elapsed_seconds"] = result.elapsed_seconds
                if result.failed:
                    event["error_code"] = result.error_code
                    if result.http_status is not None:
                        event["http_status"] = result.http_status
                if result.attempts > 1:
                    event["attempt"] = result.attempts
            progress(event)

    def run(index):
        start = monotonic()
        try:
            text = llm.complete(jobs[index][1])
        except LLMError as exc:
            return Completion(None, True, monotonic() - start,
                              exc.code, exc.http_status, exc.retryable)
        return Completion(text, False, monotonic() - start)

    def recover(results):
        if not retry_failed:
            return results
        for index, previous in enumerate(results):
            if not previous.failed or not previous.retryable:
                continue
            notify(index, "retrying", previous)
            retried = run(index)
            result = Completion(retried.text, retried.failed,
                                previous.elapsed_seconds + retried.elapsed_seconds,
                                retried.error_code, retried.http_status, retried.retryable, 2)
            results[index] = result
            notify(index, "error" if result.failed else "received", result)
        return results

    if max_workers == 1 or len(jobs) == 1:
        results = []
        for index in range(len(jobs)):
            notify(index, "submitted")
            result = run(index)
            results.append(result)
            notify(index, "error" if result.failed else "received", result)
        return recover(results)

    results = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as executor:
        pending = {}
        for index in range(len(jobs)):
            notify(index, "submitted")
            pending[executor.submit(run, index)] = index
        for future in as_completed(pending):
            index = pending[future]
            result = future.result()
            results[index] = result
            notify(index, "error" if result.failed else "received", result)
    return recover(results)
