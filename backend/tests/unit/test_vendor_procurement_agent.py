"""Unit tests for VendorProcurementManagerAgent (KAN-16).

Only the MockLLMClient is used; no real LLM calls are made.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents import AIAgent, VendorProcurementManagerAgent
from src.llm import LLMError, MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "data" / "vendor_catalog.json"

# Catering, Melbourne, 2026-12-05, 120 guests -> two candidates:
#   V-CAT-002-O1 (620000 cents, rating 4.2, capacity 120)
#   V-CAT-001-O1 (1850000 cents, rating 4.8, capacity 300)
HAPPY_RECS = json.dumps(
    {
        "recommendations": [
            {
                "vendor_id": "V-CAT-002",
                "offering_id": "V-CAT-002-O1",
                "basis_codes": ["lowest_price"],
                "reason": "Cheapest catering that fits the venue.",
            },
            {
                "vendor_id": "V-CAT-001",
                "offering_id": "V-CAT-001-O1",
                "basis_codes": ["highest_rating"],
                "reason": "Highest rated and largest capacity.",
            },
        ]
    }
)

VALID_REQUEST = {
    "event_id": "EV-2026-1205",
    "service_type": "catering",
    "event_date": "2026-12-05",
    "guest_count": 120,
    "location": "Melbourne",
}


@pytest.fixture(scope="module")
def service() -> VendorProcurementService:
    return VendorProcurementService.from_json_file(CATALOG_PATH)


def make_agent(
    service: VendorProcurementService, llm: MockLLMClient
) -> VendorProcurementManagerAgent:
    return VendorProcurementManagerAgent(llm=llm, vendor_service=service)


class TestBaseAndEnvelope:
    def test_agent_inherits_ai_agent(self, service):
        agent = make_agent(service, MockLLMClient("x"))
        assert isinstance(agent, AIAgent)

    def test_success_envelope_shape(self, service):
        agent = make_agent(service, MockLLMClient(HAPPY_RECS))
        env = agent.handle(dict(VALID_REQUEST))
        assert env["event_id"] == "EV-2026-1205"
        assert env["agent"] == "procurement"
        assert env["status"] == "success"
        assert env["timestamp"]
        assert isinstance(env["message"], str) and env["message"]
        assert set(env["data"]) == {"recommendations"}


class TestHappyPath:
    def test_deterministic_fallback_uses_catalogue_facts_without_llm(self, service):
        llm = MockLLMClient("not used")
        agent = make_agent(service, llm)

        env = agent.deterministic_fallback(dict(VALID_REQUEST))

        assert env["status"] == "success"
        assert env["data"]["fallback_used"] is True
        assert [item["offering_id"] for item in env["data"]["recommendations"]] == [
            "V-CAT-002-O1",
            "V-CAT-001-O1",
        ]
        assert llm.calls == []

    def test_returns_two_ranked_recommendations(self, service):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        env = agent.handle(dict(VALID_REQUEST))

        assert len(llm.calls) == 1
        recs = env["data"]["recommendations"]
        assert [r["rank"] for r in recs] == [1, 2]
        assert [r["offering_id"] for r in recs] == [
            "V-CAT-002-O1",
            "V-CAT-001-O1",
        ]

    def test_facts_backfilled_from_catalog(self, service):
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-CAT-002",
                            "offering_id": "V-CAT-002-O1",
                            "basis_codes": ["lowest_price"],
                            "reason": "ok",
                            # Bogus facts from the model must be ignored.
                            "total_price_cents": 1,
                            "rating": 5.0,
                        }
                    ]
                }
            )
        )
        agent = make_agent(service, llm)
        env = agent.handle(dict(VALID_REQUEST))

        rec = env["data"]["recommendations"][0]
        assert rec["vendor_name"] == "Bayside Bite Co"
        assert rec["service_type"] == "catering"
        assert rec["service_location"] == "Melbourne"
        assert rec["guest_capacity"] == 120
        assert rec["rating"] == 4.2
        assert rec["total_price_cents"] == 620000
        assert rec["event_date"] == "2026-12-05"
        assert rec["recommendation_reason"] == "ok"

    def test_prompt_contains_candidate_facts(self, service):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        agent.handle(dict(VALID_REQUEST))
        user_prompt = llm.calls[0][1]["content"]
        assert "V-CAT-001-O1" in user_prompt
        assert "V-CAT-002-O1" in user_prompt


class TestNoCandidates:
    def test_blocked_without_llm_call(self, service):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        env = agent.handle(
            {**VALID_REQUEST, "location": "Hobart"}
        )
        assert env["status"] == "blocked"
        assert llm.calls == []

    def test_blocked_when_min_rating_filters_all(self, service):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        env = agent.handle({**VALID_REQUEST, "min_rating": 4.9})
        assert env["status"] == "blocked"
        assert llm.calls == []

    def test_min_rating_keeps_qualifying_candidates(self, service):
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-CAT-001",
                            "offering_id": "V-CAT-001-O1",
                            "basis_codes": ["highest_rating"],
                            "reason": "Only candidate above 4.5.",
                        }
                    ]
                }
            )
        )
        agent = make_agent(service, llm)
        env = agent.handle({**VALID_REQUEST, "min_rating": 4.5})
        assert env["status"] == "success"
        assert [r["offering_id"] for r in env["data"]["recommendations"]] == [
            "V-CAT-001-O1"
        ]


class TestInputValidation:
    @pytest.mark.parametrize(
        "patch",
        [
            {"event_id": ""},
            {"event_date": "2026-13-01"},
            {"event_date": "05/12/2026"},
            {"guest_count": True},
            {"guest_count": -1},
            {"guest_count": "120"},
            {"min_rating": 6},
            {"min_rating": -0.1},
            {"min_rating": True},
            {"min_rating": "4.0"},
            {"customer_preferences": 123},
            {"location": "   "},
        ],
    )
    def test_needs_input(self, service, patch):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        request = {**VALID_REQUEST, **patch}
        env = agent.handle(request)
        assert env["status"] == "needs_input"
        assert llm.calls == []

    def test_needs_input_without_event_id_uses_null(self, service):
        llm = MockLLMClient(HAPPY_RECS)
        agent = make_agent(service, llm)
        env = agent.handle({})
        assert env["event_id"] is None
        assert env["status"] == "needs_input"


class TestHighestCapacityBasis:
    # Photography, Melbourne, 2026-12-06, 80 guests -> two candidates:
    #   V-PHOTO-001-O1 (2400000 cents, rating 4.9, capacity 500)
    #   V-PHOTO-002-O1 ( 890000 cents, rating 3.9, capacity 100)
    PHOTO_REQUEST = {
        **VALID_REQUEST,
        "service_type": "photography",
        "event_date": "2026-12-06",
        "guest_count": 80,
    }

    def test_true_superlative_accepted(self, service):
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-PHOTO-001",
                            "offering_id": "V-PHOTO-001-O1",
                            "basis_codes": ["highest_capacity"],
                            "reason": "Largest capacity for the guest list.",
                        },
                        {
                            "vendor_id": "V-PHOTO-002",
                            "offering_id": "V-PHOTO-002-O1",
                            "basis_codes": ["lowest_price"],
                            "reason": "Cheapest photography option.",
                        },
                    ]
                }
            )
        )
        agent = make_agent(service, llm)
        env = agent.handle(dict(self.PHOTO_REQUEST))
        assert env["status"] == "success"
        recs = env["data"]["recommendations"]
        assert [r["rank"] for r in recs] == [1, 2]
        assert recs[0]["basis_codes"] == ["highest_capacity"]
        assert recs[1]["basis_codes"] == ["lowest_price"]
        # The closed set is advertised in the prompt.
        assert "highest_capacity" in llm.calls[0][1]["content"]

    def test_false_superlative_rejected(self, service):
        # V-PHOTO-002-O1 has capacity 100, but the max is 500.
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-PHOTO-002",
                            "offering_id": "V-PHOTO-002-O1",
                            "basis_codes": ["highest_capacity"],
                            "reason": "wrong basis",
                        }
                    ]
                }
            )
        )
        agent = make_agent(service, llm)
        env = agent.handle(dict(self.PHOTO_REQUEST))
        assert env["status"] == "error"

    def test_verified_against_current_candidate_set(self, service):
        # Catering candidates on 2026-12-05: capacities 120 and 300.
        # A photography offering in the catalog has capacity 500, so a
        # catalog-wide check would reject this; the check must use the
        # current filtered candidate set, where 300 is the max.
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-CAT-001",
                            "offering_id": "V-CAT-001-O1",
                            "basis_codes": ["highest_capacity", "highest_rating"],
                            "reason": "Biggest and best rated catering option.",
                        }
                    ]
                }
            )
        )
        agent = make_agent(service, llm)
        env = agent.handle(dict(VALID_REQUEST))
        assert env["status"] == "success"
        assert env["data"]["recommendations"][0]["basis_codes"] == [
            "highest_capacity",
            "highest_rating",
        ]


class TestLlmFailures:
    def test_llm_error_returns_error(self, service):
        llm = MockLLMClient()
        llm.set_exception(LLMError("simulated outage"))
        agent = make_agent(service, llm)
        env = agent.handle(dict(VALID_REQUEST))
        assert env["status"] == "error"
        assert len(llm.calls) == 1

    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            json.dumps([1, 2, 3]),
            json.dumps({"recommendations": "nope"}),
            json.dumps({"other": []}),
            json.dumps({"recommendations": []}),
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-CAT-001",
                            "offering_id": "V-CAT-001-O1",
                            "basis_codes": [],
                            "reason": f"rec {i}",
                        }
                        for i in range(4)
                    ]
                }
            ),
        ],
    )
    def test_invalid_structure_returns_error(self, service, raw):
        agent = make_agent(service, MockLLMClient(raw))
        env = agent.handle(dict(VALID_REQUEST))
        assert env["status"] == "error"

    @pytest.mark.parametrize(
        "recs",
        [
            # Unknown candidate pair.
            [
                {
                    "vendor_id": "V-FAKE",
                    "offering_id": "V-FAKE-O1",
                    "basis_codes": [],
                    "reason": "ghost vendor",
                }
            ],
            # Cross-paired IDs (vendor from one, offering from another).
            [
                {
                    "vendor_id": "V-CAT-001",
                    "offering_id": "V-CAT-002-O1",
                    "basis_codes": [],
                    "reason": "mismatched pair",
                }
            ],
            # Repeated pair.
            [
                {
                    "vendor_id": "V-CAT-001",
                    "offering_id": "V-CAT-001-O1",
                    "basis_codes": [],
                    "reason": "first",
                },
                {
                    "vendor_id": "V-CAT-001",
                    "offering_id": "V-CAT-001-O1",
                    "basis_codes": [],
                    "reason": "duplicate",
                },
            ],
            # False superlative: V-CAT-001 is NOT the lowest price.
            [
                {
                    "vendor_id": "V-CAT-001",
                    "offering_id": "V-CAT-001-O1",
                    "basis_codes": ["lowest_price"],
                    "reason": "wrong basis",
                }
            ],
            # Unknown basis code.
            [
                {
                    "vendor_id": "V-CAT-002",
                    "offering_id": "V-CAT-002-O1",
                    "basis_codes": ["cheapest"],
                    "reason": "bad code",
                }
            ],
            # Missing / empty reason.
            [
                {
                    "vendor_id": "V-CAT-002",
                    "offering_id": "V-CAT-002-O1",
                    "basis_codes": ["lowest_price"],
                    "reason": "   ",
                }
            ],
        ],
    )
    def test_semantically_invalid_returns_error(self, service, recs):
        agent = make_agent(service, MockLLMClient(json.dumps({"recommendations": recs})))
        env = agent.handle(dict(VALID_REQUEST))
        assert env["status"] == "error"


class TestRequestShape:
    def test_non_dict_request_is_error(self, service):
        agent = make_agent(service, MockLLMClient(HAPPY_RECS))
        env = agent.handle("not a dict")  # type: ignore[arg-type]
        assert env["status"] == "error"
        assert env["event_id"] is None


class TestReceivedQuotationComparison:
    @staticmethod
    def request() -> dict:
        return {
            "event_id": "EV-QUOTE-COMPARE",
            "proposal_id": "P-QUOTE-COMPARE",
            "service_type": "catering",
            "event_date": "2026-12-05",
            "guest_count": 120,
            "location": "Melbourne",
            "service_budget_cents": 700_000,
            "quotations": [
                {
                    "quotation_id": "VQ-BAYSIDE",
                    "vendor_id": "V-CAT-002",
                    "offering_id": "V-CAT-002-O1",
                    "vendor_name": "Bayside Bite Co",
                    "service_type": "catering",
                    "service_location": "Melbourne",
                    "guest_capacity": 120,
                    "rating": 4.2,
                    "catalogue_estimate_cents": 620_000,
                    "quoted_total_cents": 600_000,
                    "available": True,
                },
                {
                    "quotation_id": "VQ-GOLDEN",
                    "vendor_id": "V-CAT-001",
                    "offering_id": "V-CAT-001-O1",
                    "vendor_name": "Golden Whisker Catering",
                    "service_type": "catering",
                    "service_location": "Melbourne",
                    "guest_capacity": 300,
                    "rating": 4.8,
                    "catalogue_estimate_cents": 1_850_000,
                    "quoted_total_cents": 800_000,
                    "available": True,
                },
            ],
        }

    def test_ranks_every_supplier_quote_and_proposes_one(self, service):
        llm = MockLLMClient(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "vendor_id": "V-CAT-002",
                            "offering_id": "V-CAT-002-O1",
                            "basis_codes": ["lowest_price", "within_budget"],
                            "reason": "Within the service budget and lowest quote.",
                        },
                        {
                            "vendor_id": "V-CAT-001",
                            "offering_id": "V-CAT-001-O1",
                            "basis_codes": ["highest_rating", "highest_capacity"],
                            "reason": "Higher rated but above the service target.",
                        },
                    ]
                }
            )
        )
        result = make_agent(service, llm).compare_received_quotations(
            self.request()
        )

        assert result["status"] == "success"
        assert result["data"]["selection_complete"] is True
        assert result["data"]["recommended_quotation_id"] == "VQ-BAYSIDE"
        assert [
            item["quotation_id"]
            for item in result["data"]["quotation_ranking"]
        ] == ["VQ-BAYSIDE", "VQ-GOLDEN"]
        assert result["data"]["fallback_used"] is False
        assert "supplier-entered quote" in llm.calls[0][0]["content"]

    def test_invalid_model_output_uses_verified_fallback(self, service):
        result = make_agent(
            service, MockLLMClient("not json")
        ).compare_received_quotations(self.request())

        assert result["status"] == "success"
        assert result["data"]["fallback_used"] is True
        assert result["data"]["recommended_quotation_id"] == "VQ-BAYSIDE"

    def test_rejected_supplier_reply_cannot_be_compared(self, service):
        request = self.request()
        request["quotations"][0]["available"] = False

        result = make_agent(service, MockLLMClient(HAPPY_RECS)).compare_received_quotations(
            request
        )

        assert result["status"] == "needs_input"
