"""MockVendorQuotationService — preset vendor quotation replies (KAN-19).

First step of the KAN-19 quotation stage: a small, deterministic mock
of the vendor side of the quotation exchange. The service takes a
specific vendor, service offering, event date and requirements, and
returns a mock quotation reply chosen by a preset scenario keyed on
``(vendor_id, offering_id, event_date, guest_count)``.

Rules:
- No randomness, no database, no LLM, no agent integration in this
  step. Scenario presets live in a JSON file
  (``data/mock_vendor_quotations.json`` by default).
- Every reply is explicitly marked ``mock: true`` and echoes the
  original request fields (plus the matching ``scenario_id``), so a
  reply can always be traced back to the request that produced it.
- Amounts are integer AUD cents (``quoted_total_cents``), per
  shared-data-and-interfaces.md; ``None`` until the vendor accepts.
- A catalog ``available: true`` does NOT imply vendor acceptance:
  this service never reads the vendor catalog. A quotation is
  ``accepted`` only when a preset scenario says so. When no scenario
  is configured for a request, the service raises ValueError instead
  of defaulting to acceptance.
- An ``accepted`` scenario only confirms capacity for the guest
  count configured on the scenario. The same vendor/offering/date
  with a different guest count has no scenario and is refused.
- ``quotation_id`` hashes canonical event, proposal, vendor, offering, date and
  guest count so different events, proposals or requirements never
  share the same quotation identifier.

This is a prototype replacement: when the real quotation interface
lands, it should keep the same request/reply contract.
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.shared.schemas import (
    require_int,
    require_non_empty_str,
    require_valid_date,
)

#: Closed set of preset vendor reply statuses.
VALID_REPLIES = ("accepted", "rejected", "pending")


class NoQuotationScenarioError(ValueError):
    """A valid enquiry has no preset supplier reply; not acceptance."""


class MockVendorQuotationService:
    """Returns preset mock vendor quotation replies, deterministically.

    One preset scenario matches at most one
    ``(vendor_id, offering_id, event_date, guest_count)`` tuple;
    duplicate scenarios are a configuration error. An ``accepted``
    scenario only confirms capacity for its configured
    ``guest_count`` — never for an arbitrary guest count.
    """

    def __init__(self, scenarios: list[dict[str, Any]]) -> None:
        self._scenarios = scenarios
        self._index: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        for scenario in scenarios:
            key = (
                scenario["vendor_id"],
                scenario["offering_id"],
                scenario["event_date"],
                scenario["guest_count"],
            )
            if key in self._index:
                raise ValueError(
                    f"duplicate mock quotation scenario for "
                    f"vendor_id={key[0]!r}, offering_id={key[1]!r}, "
                    f"event_date={key[2]!r}, guest_count={key[3]!r}"
                )
            self._index[key] = scenario

    @property
    def scenarios(self) -> list[dict[str, Any]]:
        return list(self._scenarios)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "MockVendorQuotationService":
        """Load and strictly validate a mock quotation scenario file.

        Raises ValueError when the file is not a JSON object, the
        ``scenarios`` key is missing or empty, or any scenario has an
        invalid type or value (unknown reply status, non-integer or
        negative cents, missing guest_count, missing reason,
        invalid date, duplicate scenario key).
        """
        scenario_path = Path(path)
        try:
            data = json.loads(scenario_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON in mock quotation scenarios "
                f"{scenario_path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"mock quotation scenarios {scenario_path} must be a "
                f"JSON object, got {type(data).__name__}"
            )
        if "scenarios" not in data:
            raise ValueError(
                f"mock quotation scenarios {scenario_path} must contain "
                "a 'scenarios' list of scenarios"
            )
        raw_scenarios = data["scenarios"]
        if not isinstance(raw_scenarios, list) or not raw_scenarios:
            raise ValueError(
                f"'scenarios' in {scenario_path} must be a non-empty "
                f"list, got {type(raw_scenarios).__name__}"
            )
        try:
            scenarios = [cls._parse_scenario(s) for s in raw_scenarios]
        except ValueError as exc:
            raise ValueError(
                f"invalid mock quotation scenario file {scenario_path}: "
                f"{exc}"
            ) from exc
        return cls(scenarios)

    @staticmethod
    def _parse_scenario(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(
                "scenario must be an object, "
                f"got {type(raw).__name__}: {raw!r}"
            )
        reply = require_non_empty_str(raw.get("reply"), "scenario.reply")
        if reply not in VALID_REPLIES:
            raise ValueError(
                f"scenario.reply must be one of {VALID_REPLIES}, got {reply!r}"
            )
        scenario = {
            "scenario_id": require_non_empty_str(
                raw.get("scenario_id"), "scenario.scenario_id"
            ),
            "vendor_id": require_non_empty_str(
                raw.get("vendor_id"), "scenario.vendor_id"
            ),
            "offering_id": require_non_empty_str(
                raw.get("offering_id"), "scenario.offering_id"
            ),
            "event_date": require_valid_date(
                raw.get("event_date"), "scenario.event_date"
            ),
            "guest_count": require_int(
                raw.get("guest_count"), "scenario.guest_count", minimum=0
            ),
            "reply": reply,
            "reason": require_non_empty_str(
                raw.get("reason"), "scenario.reason"
            ),
        }
        raw_cents = raw.get("quoted_total_cents")
        if reply == "accepted":
            scenario["quoted_total_cents"] = require_int(
                raw_cents, "scenario.quoted_total_cents", minimum=0
            )
        else:
            if raw_cents is not None:
                raise ValueError(
                    f"scenario.quoted_total_cents must be absent for a "
                    f"'{reply}' reply, got {raw_cents!r}"
                )
            scenario["quoted_total_cents"] = None
        return scenario

    def request_quotation(
        self,
        *,
        event_id: str,
        vendor_id: str,
        offering_id: str,
        event_date: str,
        guest_count: int,
        proposal_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the preset mock vendor reply for one quotation request.

        The lookup key is exactly ``(vendor_id, offering_id,
        event_date, guest_count)``. No matching scenario raises
        ValueError — the service never defaults to acceptance, and an
        accepted scenario never claims capacity for a guest count
        other than the one configured on the scenario.

        Raises ValueError when any argument has a wrong type or value:
        ``event_id``/``vendor_id``/``offering_id`` must be non-empty
        strings, ``event_date`` a real YYYY-MM-DD calendar date,
        ``guest_count`` a non-negative int (bools and floats
        rejected), ``proposal_id`` a non-empty string when provided.
        """
        req_event_id = require_non_empty_str(event_id, "event_id")
        req_vendor_id = require_non_empty_str(vendor_id, "vendor_id")
        req_offering_id = require_non_empty_str(offering_id, "offering_id")
        req_date = require_valid_date(event_date, "event_date")
        req_guests = require_int(guest_count, "guest_count", minimum=0)
        if proposal_id is not None:
            require_non_empty_str(proposal_id, "proposal_id")

        scenario = self._index.get(
            (req_vendor_id, req_offering_id, req_date, req_guests)
        )
        if scenario is None:
            raise NoQuotationScenarioError(
                "no mock vendor quotation scenario configured for "
                f"vendor_id={req_vendor_id!r}, offering_id="
                f"{req_offering_id!r}, event_date={req_date!r}, "
                f"guest_count={req_guests!r}; "
                "refusing to default to acceptance"
            )

        reply = scenario["reply"]
        available = {
            "accepted": True,
            "rejected": False,
            "pending": None,  # vendor has not replied; unconfirmed
        }[reply]
        # Canonical structured fields avoid ambiguous delimiter joins and
        # distinguish a missing proposal from the literal proposal ID "-".
        identity = json.dumps(
            [req_event_id, proposal_id, req_vendor_id, req_offering_id,
             req_date, req_guests],
            ensure_ascii=False, separators=(",", ":"),
        )
        quotation_id = "MQ-" + sha256(identity.encode("utf-8")).hexdigest()
        return {
            "mock": True,
            "quotation_id": quotation_id,
            "scenario_id": scenario["scenario_id"],
            "event_id": req_event_id,
            "proposal_id": proposal_id,
            "vendor_id": req_vendor_id,
            "offering_id": req_offering_id,
            "event_date": req_date,
            "guest_count": req_guests,
            "status": reply,
            "available": available,
            "quoted_total_cents": (
                scenario["quoted_total_cents"] if reply == "accepted" else None
            ),
            "reason": scenario["reason"],
        }
