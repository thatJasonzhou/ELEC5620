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


def complete_jobs(
    llm: LLMClient,
    jobs: list[tuple[str, list[dict[str, str]]]],
    *,
    max_workers: int = 1,
    stage: str,
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

    def notify(index, state, seconds=None):
        if progress is not None:
            event = {"stage": stage, "service_type": jobs[index][0], "state": state}
            if seconds is not None:
                event["elapsed_seconds"] = seconds
            progress(event)

    def run(index):
        start = monotonic()
        try:
            text = llm.complete(jobs[index][1])
        except LLMError:
            return Completion(None, True, monotonic() - start)
        return Completion(text, False, monotonic() - start)

    if max_workers == 1 or len(jobs) == 1:
        results = []
        for index in range(len(jobs)):
            notify(index, "submitted")
            result = run(index)
            results.append(result)
            notify(index, "error" if result.failed else "received", result.elapsed_seconds)
        return results

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
            notify(index, "error" if result.failed else "received", result.elapsed_seconds)
    return results
