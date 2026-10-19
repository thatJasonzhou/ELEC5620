"""Offline UI tests for the vendor procurement demo page (KAN-17).

Page-interaction tests run the real page script
(``ui/vendor_procurement_ui.py``) through ``streamlit.testing.v1.AppTest``
— no browser, no real LLM, no network. They cover the happy path, the
no-candidate (blocked) state, stale-result replacement, and the Mock/Live
mode switch (default Mock; toggling never calls the LLM or the network;
a Live submit without configuration shows an error, never a silent Mock
fall-back).

The deterministic mock LLM builder is a pure function and lives in the
Streamlit-free module ``ui/vendor_ui_helpers.py`` (importing it does not
execute the page). The unit tests import that module directly instead of
re-executing the page with ``exec_module``.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui.vendor_ui_helpers import mock_response_from_prompt

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_PATH = REPO_ROOT / "ui" / "vendor_procurement_ui.py"

RUN_TIMEOUT = 30  # seconds; Streamlit's default (3s) is too short


# Catering, Melbourne, 2026-12-05, 120 guests -> two candidates:
#   V-CAT-002-O1 (620000 cents, rating 4.2, capacity 120)
#   V-CAT-001-O1 (1850000 cents, rating 4.8, capacity 300)
# Photography, Sydney, 2026-12-06 -> zero candidates (blocked).
HAPPY = {
    "date_": date(2026, 12, 5),
    "city": "Melbourne",
    "service": "catering",
    "guests": 120,
}
NO_CANDIDATES = {
    "date_": date(2026, 12, 6),
    "city": "Sydney",
    "service": "photography",
    "guests": 50,
}


def form(t: AppTest, *, date_, city, service, guests):
    """Fill the demo form (widgets in page order) and submit it."""
    t.date_input[0].set_value(date_)
    t.selectbox[0].set_value(city)  # City
    t.number_input[0].set_value(guests)  # Number of guests
    t.selectbox[1].set_value(service)  # Service type
    t.button[0].set_value(True)
    return t.run(timeout=RUN_TIMEOUT)


class TestHappyPath:
    def test_success_with_mock_marked(self):
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)
        form(t, **HAPPY)

        assert len(t.exception) == 0, [e.value for e in t.exception]
        assert t.success, "expected a st.success message on success"
        assert "MOCK MODE" in t.warning[0].value
        assert len(t.dataframe) == 2  # candidates + recommendations
        assert t.session_state["vp_result"]["status"] == "success"
        recs = t.session_state["vp_result"]["data"]["recommendations"]
        assert [r["offering_id"] for r in recs] == [
            "V-CAT-001-O1",  # highest rating first (mock rule)
            "V-CAT-002-O1",  # then lowest price
        ]
        # V-CAT-001-O1 also holds the unique max capacity (300).
        assert recs[0]["basis_codes"] == ["highest_rating", "highest_capacity"]
        assert recs[1]["basis_codes"] == ["lowest_price"]
        assert "2026-12-05" in t.session_state["vp_conditions"]["event_date"]


class TestNoCandidates:
    def test_blocked_state_is_shown(self):
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)
        form(t, **NO_CANDIDATES)

        assert len(t.exception) == 0, [e.value for e in t.exception]
        assert len(t.success) == 0
        assert any("No candidates" in w.value for w in t.warning)
        assert t.session_state["vp_result"]["status"] == "blocked"
        # The page shows a warning instead of a candidates table when the
        # filter returns nothing; no recommendations table either.
        assert len(t.dataframe) == 0
        assert len(t.session_state["vp_candidates"]) == 0


class TestStaleResultReplacement:
    def test_failed_run_replaces_previous_success(self):
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)
        form(t, **HAPPY)
        assert t.success, "first run should succeed"

        form(t, **NO_CANDIDATES)
        assert len(t.success) == 0, "old success must be cleared after a failed run"
        assert any("No candidates" in w.value for w in t.warning)
        assert t.session_state["vp_result"]["status"] == "blocked"
        # The conditions shown with the result are THIS submission's.
        assert t.session_state["vp_conditions"]["service_type"] == "photography"
        assert t.session_state["vp_conditions"]["event_date"] == "2026-12-06"


class TestMockBuilderNoHardcodedIds:
    """The mock LLM must answer only from the prompt's current candidates.

    ``mock_response_from_prompt`` is imported directly from the
    Streamlit-free helper module (``ui/vendor_ui_helpers.py``); importing
    it never executes the page, so these checks need no AppTest run and
    no module-scope fixture.
    """

    #: Synthetic candidates with IDs that exist nowhere in the codebase.
    #: Each candidate holds exactly ONE unique superlative, so the
    #: deterministic mock rule must recommend all three, each with a
    #: single, different basis code.
    FAKE_CANDIDATES = [
        {
            "vendor_id": "VX-ALPHA",
            "offering_id": "VX-ALPHA-O9",
            "vendor_name": "Alpha Test Vendors",
            "service_type": "catering",
            "service_location": "Testville",
            "guest_capacity": 80,
            "rating": 4.1,
            "total_price_cents": 40000,  # unique lowest price
        },
        {
            "vendor_id": "VX-BETA",
            "offering_id": "VX-BETA-O9",
            "vendor_name": "Beta Test Vendors",
            "service_type": "catering",
            "service_location": "Testville",
            "guest_capacity": 90,
            "rating": 4.5,  # unique highest rating
            "total_price_cents": 90000,
        },
        {
            "vendor_id": "V-GAMMA",
            "offering_id": "V-GAMMA-O9",
            "vendor_name": "Gamma Test Vendors",
            "service_type": "catering",
            "service_location": "Testville",
            "guest_capacity": 200,  # unique highest capacity
            "rating": 3.5,
            "total_price_cents": 90000,
        },
    ]

    def _prompt(self, marker_extra=""):
        return (
            "Recommend vendors.\n"
            f"Candidates (facts, already verified by code):{marker_extra}\n"
            + json.dumps(self.FAKE_CANDIDATES, indent=2)
            + "\nRespond with STRICT JSON only."
        )

    def test_recs_come_from_prompt_candidates_only(self):
        raw = mock_response_from_prompt(
            [
                {"role": "system", "content": "s"},
                {"role": "user", "content": self._prompt()},
            ]
        )
        parsed = json.loads(raw)
        recs = parsed["recommendations"]

        ids = {r["vendor_id"] for r in recs}
        assert ids <= {"VX-ALPHA", "VX-BETA", "V-GAMMA"}
        assert not (ids & {"V-CAT-001", "V-CAT-002", "V-PHOTO-001", "V-PHOTO-002"})

        # Deterministic mock rule: highest rating, lowest price, then
        # highest capacity (de-duplicated) — all three candidates are
        # recommended exactly once.
        assert [r["vendor_id"] for r in recs] == [
            "VX-BETA",
            "VX-ALPHA",
            "V-GAMMA",
        ]
        by_id = {r["vendor_id"]: r for r in recs}
        assert by_id["VX-BETA"]["basis_codes"] == ["highest_rating"]
        assert by_id["VX-BETA"]["offering_id"] == "VX-BETA-O9"
        assert by_id["V-GAMMA"]["basis_codes"] == ["highest_capacity"]
        assert by_id["VX-ALPHA"]["basis_codes"] == ["lowest_price"]
        # Reasons quote the current candidates' facts.
        assert "Alpha Test Vendors" in by_id["VX-ALPHA"]["reason"]

    def test_missing_marker_returns_empty_recommendations(self):
        parsed = json.loads(
            mock_response_from_prompt(
                [{"role": "user", "content": "no candidates here"}]
            )
        )
        assert parsed["recommendations"] == []

    def test_empty_candidate_list_returns_empty_recommendations(self):
        prompt = (
            "Candidates (facts, already verified by code):\n[]\nRespond."
        )
        parsed = json.loads(
            mock_response_from_prompt(
                [{"role": "user", "content": prompt}]
            )
        )
        assert parsed["recommendations"] == []


class TestModeSwitch:
    """Mock (default) vs Live mode: the API is only ever called on
    submit, a toggle never calls anything, and a failed Live run never
    silently falls back to Mock."""

    def test_mode_radio_defaults_to_mock(self):
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)
        # The only radio in the form is the mode switch.
        assert len(t.radio) == 1
        assert t.radio[0].value == "mock"
        assert "MOCK MODE" in t.warning[0].value

    def test_mode_toggle_makes_zero_llm_or_http_calls(self, monkeypatch):
        """Toggling the radio re-renders the page only: no client is
        built, no LLM or HTTP call happens, in either mode."""
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)

        def _boom(*args, **kwargs):
            raise AssertionError("no HTTP call before/without a submit")

        with monkeypatch.context() as m:
            m.setattr("urllib.request.urlopen", _boom)
            # Toggle to Live — the page must simply re-render.
            t.radio[0].set_value("live")
            t = t.run(timeout=RUN_TIMEOUT)
            assert len(t.exception) == 0, [e.value for e in t.exception]
            # Banner follows the radio (info, not the mock warning).
            assert "MOCK MODE" not in " ".join(w.value for w in t.warning)
            assert any("LIVE MODE" in i.value for i in t.info)
            # No result or candidates were produced by the toggle.
            assert t.session_state.get("vp_result") is None
            assert t.session_state.get("vp_candidates") is None

            # Toggle back to Mock — same guarantees.
            t.radio[0].set_value("mock")
            t = t.run(timeout=RUN_TIMEOUT)
            assert len(t.exception) == 0, [e.value for e in t.exception]
            assert "MOCK MODE" in t.warning[0].value
            assert t.session_state.get("vp_result") is None

    def test_live_submit_without_config_shows_error(self, monkeypatch):
        """Live submit with missing ELEC5620_LLM_* env vars: error
        envelope, mode recorded as 'live', previous result cleared,
        and NO silent fall-back to Mock (no recommendations, no
        HTTP call)."""
        t = AppTest.from_file(str(UI_PATH)).run(timeout=RUN_TIMEOUT)
        # A successful Mock run first, so there is a "previous result".
        form(t, **HAPPY)
        assert t.session_state["vp_result"]["status"] == "success"

        def _boom(*args, **kwargs):
            raise AssertionError("a failed Live run must not call the API")

        for var in ("ELEC5620_LLM_BASE_URL", "ELEC5620_LLM_API_KEY", "ELEC5620_LLM_MODEL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("urllib.request.urlopen", _boom)

        t.radio[0].set_value("live")
        form(t, **HAPPY)

        assert len(t.exception) == 0, [e.value for e in t.exception]
        result = t.session_state["vp_result"]
        assert result["status"] == "error"
        assert result["agent"] == "procurement"
        assert "Live mode setup failed" in result["message"]
        assert "ELEC5620_LLM" in result["message"]
        # No silent Mock fall-back: empty data, no success banner, and
        # the previous successful result was replaced.
        assert result["data"] == {}
        assert len(t.success) == 0
        # The mode of THIS submission is recorded and shown.
        assert t.session_state["vp_conditions"]["mode"] == "live"
        result_md = [
            e for e in t.markdown if "Submitted conditions" in e.value
        ]
        assert result_md and "Mode: live" in result_md[0].value
