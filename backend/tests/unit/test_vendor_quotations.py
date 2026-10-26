"""Unit tests for the mock vendor quotation service (KAN-19)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.vendor_quotation_service import (
    VALID_REPLIES,
    MockVendorQuotationService,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = REPO_ROOT / "data" / "mock_vendor_quotations.json"

REQUEST_BASE = {
    "event_id": "EV001",
    "proposal_id": "P-001",
    "event_date": "2026-12-05",
    "guest_count": 120,
}


@pytest.fixture(scope="module")
def service() -> MockVendorQuotationService:
    return MockVendorQuotationService.from_json_file(SCENARIO_PATH)


@pytest.fixture()
def empty(tmp_path: Path) -> Path:
    def write(name: str, payload: object) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return write


# ---------------------------------------------------------------------------
# The three preset replies
# ---------------------------------------------------------------------------


def _request(overrides: dict) -> dict:
    """Build one request dict; never mix ``**REQUEST_BASE`` with
    keyword arguments that duplicate its keys (TypeError)."""
    request = dict(REQUEST_BASE)
    request.update(overrides)
    return request


class TestAcceptedReply:
    def test_accepted_returns_mock_quotation(self, service):
        reply = service.request_quotation(
            **_request(
                {"vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1"}
            )
        )
        assert reply["mock"] is True
        assert reply["status"] == "accepted"
        assert reply["available"] is True
        assert reply["scenario_id"] == "MOCK-Q-ACCEPT-001"
        # Quote is an integer number of AUD cents.
        assert reply["quoted_total_cents"] == 1850000
        assert isinstance(reply["quoted_total_cents"], int)
        assert isinstance(reply["reason"], str) and reply["reason"].strip()

    def test_accepted_reply_traces_to_request(self, service):
        reply = service.request_quotation(**_request({"vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1"}))
        assert reply["event_id"] == "EV001"
        assert reply["proposal_id"] == "P-001"
        assert reply["vendor_id"] == "V-CAT-001"
        assert reply["offering_id"] == "V-CAT-001-O1"
        assert reply["event_date"] == "2026-12-05"
        assert reply["guest_count"] == 120
        assert reply["quotation_id"].startswith("MQ-")

    def test_accepted_is_deterministic(self, service):
        request = {
            **REQUEST_BASE,
            "vendor_id": "V-CAT-001",
            "offering_id": "V-CAT-001-O1",
        }
        assert service.request_quotation(**request) == service.request_quotation(
            **request
        )


class TestRejectedReply:
    def test_rejected_with_reason(self, service):
        reply = service.request_quotation(**_request({"vendor_id": "V-PHOTO-001",
            "offering_id": "V-PHOTO-001-O2",
            "guest_count": 80,}))
        assert reply["mock"] is True
        assert reply["status"] == "rejected"
        assert reply["available"] is False
        assert reply["quoted_total_cents"] is None
        assert reply["scenario_id"] == "MOCK-Q-REJECT-001"
        assert "Sydney" in reply["reason"]
        # Still traceable to the request.
        assert reply["vendor_id"] == "V-PHOTO-001"
        assert reply["event_id"] == "EV001"


class TestPendingReply:
    def test_pending_is_unconfirmed(self, service):
        reply = service.request_quotation(**_request({"vendor_id": "V-CAT-002",
            "offering_id": "V-CAT-002-O1",}))
        assert reply["mock"] is True
        assert reply["status"] == "pending"
        # Neither accepted nor rejected: unconfirmed.
        assert reply["available"] is None
        assert reply["quoted_total_cents"] is None
        assert reply["scenario_id"] == "MOCK-Q-PENDING-001"
        assert "not replied" in reply["reason"].lower()


# ---------------------------------------------------------------------------
# No default acceptance
# ---------------------------------------------------------------------------


class TestNoDefaultAcceptance:
    def test_unconfigured_request_raises(self, service):
        # No mock scenario is configured for this supplier/date,
        # regardless of its catalogue availability.
        # available=true in the catalog must NOT imply vendor acceptance.
        with pytest.raises(ValueError, match="no mock vendor quotation scenario"):
            service.request_quotation(**_request({"vendor_id": "V-PHOTO-002",
                "offering_id": "V-PHOTO-002-O1",
                "event_date": "2026-12-07",
                "guest_count": 100,}))

    def test_unknown_vendor_raises(self, service):
        with pytest.raises(ValueError, match="refusing to default to acceptance"):
            service.request_quotation(**_request({"vendor_id": "V-NOPE", "offering_id": "V-NOPE-O1"}))

    def test_wrong_date_for_configured_vendor_raises(self, service):
        # Same vendor+offering as the accepted scenario, different date.
        with pytest.raises(ValueError, match="no mock vendor quotation scenario"):
            service.request_quotation(**_request({"vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "event_date": "2026-12-06",}))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestRequestValidation:
    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("event_id", ""),
            ("event_id", None),
            ("vendor_id", ""),
            ("offering_id", "  "),
        ],
    )
    def test_non_string_id_rejected(self, service, field, bad_value):
        request = {
            **REQUEST_BASE,
            "vendor_id": "V-CAT-001",
            "offering_id": "V-CAT-001-O1",
            field: bad_value,
        }
        with pytest.raises(ValueError):
            service.request_quotation(**request)

    @pytest.mark.parametrize("bad_date", ["2026-02-30", "2026-13-01", "20261205", None])
    def test_invalid_event_date_rejected(self, service, bad_date):
        with pytest.raises(ValueError):
            service.request_quotation(**_request({"vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "event_date": bad_date,}))

    @pytest.mark.parametrize(
        ("bad_guests", "min_note"),
        [
            (True, 0),
            (120.0, 0),
            ("120", 0),
            (-1, 0),
        ],
    )
    def test_invalid_guest_count_rejected(self, service, bad_guests, min_note):
        with pytest.raises(ValueError):
            service.request_quotation(**_request({"vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "guest_count": bad_guests,}))

    def test_empty_proposal_id_rejected(self, service):
        with pytest.raises(ValueError, match="proposal_id"):
            service.request_quotation(**_request({"vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "proposal_id": "  ",}))

    def test_missing_proposal_id_is_optional(self, service):
        reply = service.request_quotation(
            **{k: v for k, v in REQUEST_BASE.items() if k != "proposal_id"},
            vendor_id="V-CAT-001",
            offering_id="V-CAT-001-O1",
        )
        assert reply["proposal_id"] is None


# ---------------------------------------------------------------------------
# Strict scenario loading
# ---------------------------------------------------------------------------


class TestScenarioFileLoading:
    def test_missing_scenarios_key(self, empty):
        with pytest.raises(ValueError, match="'scenarios'"):
            MockVendorQuotationService.from_json_file(
                empty("bad.json", {"nope": 1})
            )

    @pytest.mark.parametrize("payload", [{"scenarios": []}])
    def test_empty_scenarios(self, empty, payload):
        with pytest.raises(ValueError, match="non-empty"):
            MockVendorQuotationService.from_json_file(empty("bad.json", payload))

    def test_non_object_root(self, empty):
        with pytest.raises(ValueError, match="must be a JSON object"):
            MockVendorQuotationService.from_json_file(empty("bad.json", []))

    def test_invalid_json(self, empty):
        path = empty("bad.json", None)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSON"):
            MockVendorQuotationService.from_json_file(path)

    def test_unknown_reply_status(self, empty):
        with pytest.raises(ValueError, match="scenario.reply"):
            MockVendorQuotationService.from_json_file(
                empty(
                    "bad.json",
                    {
                        "scenarios": [
                            {
                                "scenario_id": "S1",
                                "vendor_id": "V1",
                                "offering_id": "V1-O1",
                                "event_date": "2026-12-05",
                                "guest_count": 120,
                                "reply": "maybe",
                                "reason": "r",
                            }
                        ]
                    },
                )
            )

    @pytest.mark.parametrize(
        ("override", "match"),
        [
            ({"quoted_total_cents": -5}, "quoted_total_cents"),
            ({"quoted_total_cents": 18.5}, "quoted_total_cents"),
            ({"quoted_total_cents": True}, "quoted_total_cents"),
            ({"reason": "  "}, "scenario.reason"),
            ({"event_date": "2026-02-30"}, "scenario.event_date"),
        ],
    )
    def test_invalid_accepted_fields(self, empty, override, match):
        scenario = {
            "scenario_id": "S1",
            "vendor_id": "V1",
            "offering_id": "V1-O1",
            "event_date": "2026-12-05",
            "guest_count": 120,
            "reply": "accepted",
            "reason": "ok",
            "quoted_total_cents": 100,
        }
        scenario.update(override)
        with pytest.raises(ValueError, match=match):
            MockVendorQuotationService.from_json_file(
                empty("bad.json", {"scenarios": [scenario]})
            )

    def test_rejected_with_cents_is_invalid(self, empty):
        with pytest.raises(ValueError, match="must be absent"):
            MockVendorQuotationService.from_json_file(
                empty(
                    "bad.json",
                    {
                        "scenarios": [
                            {
                                "scenario_id": "S1",
                                "vendor_id": "V1",
                                "offering_id": "V1-O1",
                                "event_date": "2026-12-05",
                                "guest_count": 120,
                                "reply": "rejected",
                                "reason": "no",
                                "quoted_total_cents": 100,
                            }
                        ]
                    },
                )
            )

    def test_duplicate_scenario_key(self, empty):
        scenario = {
            "scenario_id": "S1",
            "vendor_id": "V1",
            "offering_id": "V1-O1",
            "event_date": "2026-12-05",
            "guest_count": 120,
            "reply": "pending",
            "reason": "r",
        }
        with pytest.raises(ValueError, match="duplicate mock quotation scenario"):
            MockVendorQuotationService.from_json_file(
                empty("bad.json", {"scenarios": [scenario, dict(scenario)]})
            )

    def test_duplicate_scenario_key_in_constructor(self):
        scenario = {
            "scenario_id": "S1",
            "vendor_id": "V1",
            "offering_id": "V1-O1",
            "event_date": "2026-12-05",
            "guest_count": 120,
            "reply": "pending",
            "reason": "r",
            "quoted_total_cents": None,
        }
        with pytest.raises(ValueError, match="duplicate mock quotation scenario"):
            MockVendorQuotationService([scenario, dict(scenario)])


# ---------------------------------------------------------------------------
# Sanity: the shipped scenario file covers all three reply types
# ---------------------------------------------------------------------------


class TestShippedScenarios:
    def test_all_three_replies_present(self, service):
        replies = {s["reply"] for s in service.scenarios}
        assert replies == set(VALID_REPLIES)

    def test_scenario_property_returns_copy(self, service):
        first = service.scenarios
        first.append({"bogus": True})
        assert "bogus" not in {str(s.get("scenario_id")) for s in service.scenarios}


class TestRequestSpecificReplies:
    def test_exact_guest_count_selects_supplier_reply(self, service):
        reply = service.request_quotation(**_request({
            "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1",
            "guest_count": 120,
        }))
        assert reply["status"] == "accepted"
        assert reply["guest_count"] == 120

    @pytest.mark.parametrize("guests", [1, 50, 80, 299])
    def test_unconfigured_guest_count_is_not_accepted(self, service, guests):
        with pytest.raises(ValueError, match="no mock vendor quotation scenario"):
            service.request_quotation(**_request({
                "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1",
                "guest_count": guests,
            }))

    @pytest.mark.parametrize("valid_date", ["2026-05-12", "2026-12-31"])
    def test_valid_unconfigured_dates_reach_scenario_lookup(self, service, valid_date):
        with pytest.raises(ValueError, match="no mock vendor quotation scenario"):
            service.request_quotation(**_request({
                "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1",
                "event_date": valid_date,
            }))

    def test_invalid_date_is_rejected_before_lookup(self, service):
        with pytest.raises(ValueError, match="not a valid calendar date"):
            service.request_quotation(**_request({
                "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1",
                "event_date": "2026-02-30",
            }))

    def test_quotation_identity_distinguishes_requests(self, service):
        base = _request({"vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1"})
        variants = [base, {**base, "event_id": "EV002"},
                    {**base, "proposal_id": "P-002"}]
        ids = [service.request_quotation(**request)["quotation_id"] for request in variants]
        assert len(set(ids)) == len(variants)

    def test_delimiters_and_missing_proposals_do_not_alias(self, service):
        base = _request({"vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1"})
        variants = [
            {**base, "event_id": "EV-A", "proposal_id": "B"},
            {**base, "event_id": "EV", "proposal_id": "A-B"},
            {**base, "proposal_id": None}, {**base, "proposal_id": "-"},
        ]
        ids = [service.request_quotation(**request)["quotation_id"] for request in variants]
        assert len(set(ids)) == len(variants)

    def test_guest_count_changes_quotation_identity(self, service):
        base = _request({
            "vendor_id": "V-CAT-001", "offering_id": "V-CAT-001-O1",
            "event_date": "2026-12-16", "guest_count": 50,
        })
        first = service.request_quotation(**base)
        second = service.request_quotation(**{**base, "guest_count": 80})
        assert first["quotation_id"] != second["quotation_id"]
