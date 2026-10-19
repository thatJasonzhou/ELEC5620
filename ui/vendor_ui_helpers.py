"""Pure helper functions for the vendor procurement UI (KAN-17).

Extracted from ``vendor_procurement_ui.py`` so that unit tests can import
them as a plain module. Importing this module must never execute a
Streamlit page (no ``st.form``, no ``main()``); it only contains
deterministic, Streamlit-free logic.

The demo page (``ui/vendor_procurement_ui.py``) imports
``mock_response_from_prompt`` from here, so page and tests exercise the
exact same mock LLM builder.
"""
from __future__ import annotations

import json
from typing import Any

#: Marker inside the agent's user prompt that precedes the candidate list.
CANDIDATES_MARKER = "Candidates (facts, already verified by code):"


def basis_codes(
    candidate: dict[str, Any], all: list[dict[str, Any]]
) -> list[str]:
    """Superlative codes that are factually TRUE for ``candidate``.

    A code is returned only when the candidate strictly holds the extreme
    across ALL candidates (unique minimum / maximum), mirroring the rule
    the agent itself re-verifies. Ties produce no code.
    """
    codes: list[str] = []
    if candidate["total_price_cents"] == min(
        c["total_price_cents"] for c in all
    ) and sum(
        1 for c in all if c["total_price_cents"] == candidate["total_price_cents"]
    ) == 1:
        codes.append("lowest_price")
    if candidate["rating"] == max(c["rating"] for c in all) and sum(
        1 for c in all if c["rating"] == candidate["rating"]
    ) == 1:
        codes.append("highest_rating")
    if candidate["guest_capacity"] == max(c["guest_capacity"] for c in all) and sum(
        1 for c in all if c["guest_capacity"] == candidate["guest_capacity"]
    ) == 1:
        codes.append("highest_capacity")
    return codes


def mock_recommendations(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministically rank 1-3 of the given candidates (MOCK logic)."""
    valid = [
        c
        for c in candidates
        if isinstance(c, dict)
        and isinstance(c.get("vendor_id"), str)
        and c.get("vendor_id").strip()
        and isinstance(c.get("offering_id"), str)
        and c.get("offering_id").strip()
    ]

    def price(c: dict[str, Any]) -> int:
        value = c.get("total_price_cents")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    def rating(c: dict[str, Any]) -> float:
        value = c.get("rating")
        return float(value) if isinstance(value, (int, float)) and not isinstance(
            value, bool
        ) else 0.0

    def capacity(c: dict[str, Any]) -> int:
        value = c.get("guest_capacity")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    def pick(key) -> dict[str, Any] | None:
        for c in valid:
            if key(c) is not None:
                return c
        return None

    def key_hint(c: dict[str, Any]) -> str | None:
        codes = basis_codes(c, valid)
        if "highest_rating" in codes:
            return "highest rating"
        if "lowest_price" in codes:
            return "lowest price"
        if "highest_capacity" in codes:
            return "highest capacity"
        return None

    ordered: list[tuple[dict[str, Any], str | None]] = []
    seen: set[tuple[str, str]] = set()

    def take(c: dict[str, Any] | None) -> None:
        if c is None:
            return
        pair = (c["vendor_id"], c["offering_id"])
        if pair in seen:
            return
        seen.add(pair)
        ordered.append((c, key_hint(c)))

    if not valid:
        return []

    # Rank 1: best rating (tie: lowest price, then candidate order).
    take(pick(lambda c: c if rating(c) == max(rating(x) for x in valid) else None))
    # Rank 2: lowest price (tie: highest rating, then candidate order).
    take(pick(lambda c: c if price(c) == min(price(x) for x in valid) else None))
    # Rank 3: highest capacity (tie: highest rating, then candidate order).
    take(pick(lambda c: c if capacity(c) == max(capacity(x) for x in valid) else None))
    ordered = ordered[:3]

    recommendations = []
    for index, (c, why) in enumerate(ordered):
        facts = (
            f"{c['vendor_name']} ({c['vendor_id']}) offers {c['service_type']} in "
            f"{c['service_location']} for AUD {price(c) / 100:,.2f} per event, "
            f"rated {rating(c):.1f} with capacity for {capacity(c)} guests."
        )
        highlight = (
            f" Among the candidates it has the {why}."
            if why
            else " It is a solid match within the candidate set."
        )
        recommendations.append(
            {
                "vendor_id": c["vendor_id"],
                "offering_id": c["offering_id"],
                "basis_codes": basis_codes(c, valid),
                "reason": facts + highlight,
            }
        )
    return recommendations


def mock_response_from_prompt(messages: list[dict[str, str]]) -> str:
    """Build a mock LLM response from the candidates in the user prompt.

    The agent embeds the filtered candidate list (verified by code) as a
    JSON array right after :data:`CANDIDATES_MARKER`; this function reads
    it back and answers strictly from those candidates, so no vendor ID
    is ever hardcoded here.
    """
    user_prompt = next(
        (m["content"] for m in messages if m.get("role") == "user"), ""
    )
    marker_pos = user_prompt.find(CANDIDATES_MARKER)
    if marker_pos < 0:
        return json.dumps(
            {
                "recommendations": [],
                "_mock_error": "candidate list not found in prompt",
            }
        )
    array_start = user_prompt.find("[", marker_pos)
    if array_start < 0:
        return json.dumps(
            {"recommendations": [], "_mock_error": "candidate array not found"}
        )
    try:
        candidates, _ = json.JSONDecoder().raw_decode(user_prompt[array_start:])
    except json.JSONDecodeError:
        return json.dumps(
            {"recommendations": [], "_mock_error": "candidate array unreadable"}
        )
    if not isinstance(candidates, list):
        return json.dumps(
            {"recommendations": [], "_mock_error": "candidates not a list"}
        )
    return json.dumps({"recommendations": mock_recommendations(candidates)})
