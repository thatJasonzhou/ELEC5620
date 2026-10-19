"""Vendor Procurement demo page (KAN-17) — Streamlit, Mock + Live modes.

A simple English UI for the Vendor Procurement Manager Agent. The page:

- runs the EXISTING ``VendorProcurementService`` (deterministic candidate
  filtering) and the EXISTING ``VendorProcurementManagerAgent`` (LLM
  recommendation stage) without changing their business logic;
- offers a mode switch above the form (Mock by default):
  - Mock: ``MockLLMClient`` with a deterministic builder that derives its
    recommendation from the candidate set embedded in the agent's prompt
    — no hardcoded vendor IDs, no network, no real LLM call. The builder
    lives in the Streamlit-free module ``ui/vendor_ui_helpers.py`` so
    unit tests can import it without executing this page;
  - Live: ``CampusQwenClient.from_env()`` reads only the
    ``ELEC5620_LLM_*`` environment variables at submit time; the API is
    called only when the form is submitted (never on page load or when
    toggling the switch), and a configuration/transport failure is
    shown as an ``error`` envelope — never a silent fall-back to Mock;
- shows every status clearly: success (ranked recommendations),
  ``blocked`` (no candidates), ``needs_input`` / ``error`` (input problem);
- keeps the submitted conditions (including the mode) together with the
  result in ``st.session_state`` so a new (even failed) submission never
  leaves a previous successful result displayed.

Scope: recommendation demo only. No booking, no payment, no persistence.
Configuration is read from process environment variables only, and
credentials are never displayed or logged.

Run from the repository root:

    py -3 -m streamlit run ui/vendor_procurement_ui.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from src.agents import VendorProcurementManagerAgent
from src.llm import CampusQwenClient, LLMError, MockLLMClient
from src.services.vendor_procurement_service import VendorProcurementService
from ui.vendor_ui_helpers import mock_response_from_prompt

CATALOG_PATH = REPO_ROOT / "data" / "vendor_catalog.json"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
_service = VendorProcurementService.from_json_file(CATALOG_PATH)


def _available_dates() -> list[str]:
    dates = sorted(
        {
            slot.date
            for vendor in _service.catalog
            for offering in vendor.service_offerings
            for slot in offering.availability
            if slot.available
        }
    )
    return dates


def _service_locations() -> list[str]:
    return sorted(
        {
            offering.service_location
            for vendor in _service.catalog
            for offering in vendor.service_offerings
        }
    )


def _service_types() -> list[str]:
    return sorted(
        {
            offering.service_type
            for vendor in _service.catalog
            for offering in vendor.service_offerings
        }
    )


def _candidate_rows(
    service_type: str,
    event_date: str,
    guests: int,
    location: str,
    min_rating: float | None,
) -> list[dict[str, Any]]:
    """Same deterministic filter the agent uses, for display purposes."""
    candidates = _service.filter_vendors(
        service_type=service_type,
        date=event_date,
        guest_count=guests,
        location=location,
    )
    if min_rating is not None:
        candidates = [c for c in candidates if c["rating"] >= min_rating]
    return candidates


def _candidates_table_rows(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "Vendor ID": c["vendor_id"],
            "Offering ID": c["offering_id"],
            "Vendor": c["vendor_name"],
            "Service": c["service_type"],
            "City": c["service_location"],
            "Capacity (guests)": c["guest_capacity"],
            "Rating": c["rating"],
            "Est. whole-event price (AUD)": c["total_price_cents"] / 100,
        }
        for c in candidates
    ]


def _recs_table_rows(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Rank": r["rank"],
            "Vendor": r["vendor_name"],
            "Vendor ID / Offering": f"{r['vendor_id']} / {r['offering_id']}",
            "Est. whole-event price (AUD)": r["total_price_cents"] / 100,
            "Rating": r["rating"],
            "Capacity (guests)": r["guest_capacity"],
            "Basis (code-verified)": ", ".join(r["basis_codes"]) or "(none)",
            "Reason (AI-generated, not fully fact-verified)": r["recommendation_reason"],
        }
        for r in recommendations
    ]


def render_results() -> None:
    """Render the result of the LAST submission (never a stale one)."""
    result = st.session_state.get("vp_result")
    if result is None:
        return

    st.subheader("Result")

    # The submitted conditions of THIS run travel with the result.
    conditions = st.session_state.get("vp_conditions", {})
    st.markdown(
        "**Submitted conditions:** "
        + " · ".join(
            f"{label}: {value}"
            for label, value in [
                ("Mode", conditions.get("mode", "mock")),
                ("Service", conditions.get("service_type")),
                ("Date", conditions.get("event_date")),
                ("City", conditions.get("location")),
                ("Guests", conditions.get("guest_count")),
                (
                    "Min rating",
                    conditions.get("min_rating")
                    if conditions.get("min_rating") is not None
                    else "not set",
                ),
                ("Preferences", conditions.get("customer_preferences") or "(none)"),
            ]
        )
    )

    status = result.get("status")
    message = result.get("message", "")

    if status == "success":
        st.success(message)
        recommendations = (result.get("data") or {}).get("recommendations", [])
        if recommendations:
            st.dataframe(_recs_table_rows(recommendations), width="stretch")
        else:
            st.warning("Success, but no recommendations were returned.")
    elif status == "blocked":
        st.warning(f"No candidates — request blocked. {message}")
    elif status == "needs_input":
        st.error(f"Input problem — please fix the highlighted fields. {message}")
    else:  # "error"
        st.error(f"Run failed. {message}")


def main() -> None:
    st.set_page_config(
        page_title="Vendor Procurement Demo",
        page_icon="🤖",
        layout="wide",
    )
    st.title("Vendor Procurement Manager — Recommendation Demo")

    dates = _available_dates()
    cities = _service_locations()
    types = _service_types()

    st.info(
        "The catalog has example availability on "
        f"**{', '.join(dates)}** in **{', '.join(cities)}** "
        f"for **{', '.join(types)}**. Pick one of those to get candidates."
    )

    st.session_state.setdefault("vp_result", None)
    st.session_state.setdefault("vp_candidates", None)

    # Mode switch OUTSIDE the form: toggling it only re-renders the page —
    # it can never submit the form, so it can never build a client or call
    # the API. The banner below renders from this call's return value, so
    # it is always in sync with the radio (no pre-reading session_state).
    mode = st.radio(
        "Mode",
        options=["mock", "live"],
        index=0,
        horizontal=True,
        key="vp_mode",
        help=(
            "Mock: deterministic offline recommendation (default, no "
            "network). Live: calls the real Campus Qwen API via the "
            "ELEC5620_LLM_* environment variables — the API is only "
            "called when the form is submitted."
        ),
    )
    if mode == "live":
        st.info(
            "**LIVE MODE** — Recommendations are produced by the real "
            "Campus Qwen API. The API is called **only when you submit the "
            "form** (never on page load or when switching modes). "
            "Configuration comes from the `ELEC5620_LLM_*` environment "
            "variables; keys are never displayed. Prices are fictional "
            "catalog estimates in AUD, not confirmed quotations."
        )
    else:
        st.warning(
            "⚠️ **MOCK MODE** — Recommendations are produced by a simulated "
            "(mock) LLM. No real LLM or API call is made. Prices are fictional "
            "catalog estimates in AUD, not confirmed quotations."
        )

    with st.form("vp_form"):
        st.markdown("### Event details")
        event_date = st.date_input(
            "Event date",
            value=date.fromisoformat(dates[0]) if dates else date(2026, 12, 5),
        )
        city = st.selectbox(
            "City",
            options=cities,
            index=0 if cities else 0,
        )
        guests = st.number_input(
            "Number of guests",
            min_value=0,
            max_value=10_000,
            value=120,
            step=1,
        )
        service_type = st.selectbox(
            "Service type",
            options=types,
            index=0 if types else 0,
        )
        min_rating = st.number_input(
            "Minimum vendor rating (optional — 0 means no minimum)",
            min_value=0.0,
            max_value=5.0,
            value=0.0,
            step=0.1,
            format="%.1f",
        )
        preferences = st.text_area(
            "Customer preferences (optional, soft guidance only)",
            value="",
            height=100,
        )
        submitted = st.form_submit_button("Get recommendations")

    if submitted:
        # A new submission always replaces any previous result so a
        # failed run cannot leave an old successful result on screen.
        st.session_state.vp_result = None
        st.session_state.vp_candidates = None

        event_date_iso = event_date.isoformat()
        min_rating_value: float | None = min_rating if min_rating > 0 else None
        candidates = _candidate_rows(
            service_type, event_date_iso, int(guests), city, min_rating_value
        )
        st.session_state.vp_candidates = candidates

        request = {
            "event_id": f"EV-{event_date_iso.replace('-', '')}-UI",
            "service_type": service_type,
            "event_date": event_date_iso,
            "guest_count": int(guests),
            "location": city,
            "customer_preferences": preferences.strip(),
        }
        if min_rating_value is not None:
            request["min_rating"] = min_rating_value

        event_id = request["event_id"]

        # The LLM client is built ONLY at submit time, per the selected
        # mode. Nothing here is ever called on page load or on a mode
        # toggle — a mode change simply re-renders the page.
        if mode == "live":
            try:
                llm: CampusQwenClient | MockLLMClient = CampusQwenClient.from_env()
            except LLMError as exc:
                # Configuration/initialisation failed before any API call.
                # Show the problem as a normal error envelope — never
                # silently fall back to Mock. The message names only
                # variable names, never their values.
                envelope = {
                    "event_id": event_id,
                    "agent": "procurement",
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "status": "error",
                    "message": f"Live mode setup failed: {exc}",
                    "data": {},
                }
            else:
                envelope = VendorProcurementManagerAgent(
                    llm=llm,
                    vendor_service=_service,
                ).handle(request)
        else:
            envelope = VendorProcurementManagerAgent(
                llm=MockLLMClient(mock_response_from_prompt),
                vendor_service=_service,
            ).handle(request)

        st.session_state.vp_result = envelope
        st.session_state.vp_conditions = {
            "mode": "live" if mode == "live" else "mock",
            "service_type": service_type,
            "event_date": event_date_iso,
            "location": city,
            "guest_count": int(guests),
            "min_rating": min_rating_value,
            "customer_preferences": preferences.strip(),
        }

    st.markdown("### Candidates (deterministic code filter, pre-LLM)")
    candidates = st.session_state.get("vp_candidates")
    if candidates is None:
        st.caption("Submit the form to run the filter.")
    elif not candidates:
        st.warning(
            "No candidate vendors match these conditions. Try one of the "
            "example dates/cities shown above."
        )
    else:
        st.dataframe(_candidates_table_rows(candidates), width="stretch")

    render_results()


main()
