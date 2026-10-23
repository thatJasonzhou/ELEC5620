"""Standalone Operations MVP page; import render_operations into the team UI.

Run: python -m streamlit run ui/event_operations_ui.py
No LLM/network calls. State is session-local and lost on server restart.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from examples.operations_example import build_demo_request
from src.agents.event_operations import EventOperationsAgent
from src.llm import MockLLMClient
from src.services.event_operations_service import InMemoryEventOperationsService
from src.shared.schemas import TASK_STATUSES


def render_operations():
    st.title("Event Operations")
    st.caption("Approved plan → confirmed vendors → execution tasks → progress")
    st.info("MVP · Memory-only session · No AI inference or real supplier/payment calls. "
            "Execution complete does not mean financially settled or event closed.")
    if "ops_service" not in st.session_state:
        st.session_state.ops_service = InMemoryEventOperationsService()
    agent = EventOperationsAgent(MockLLMClient(), st.session_state.ops_service)
    st.subheader("1. Receive the handoff")
    st.caption("Paste the current approved Planner proposal and complete successful Procurement result. "
               "Demo inputs are separate and explicitly simulated.")
    if st.button("Load MOCK demo inputs", key="ops_demo"):
        st.session_state.ops_input = json.dumps(build_demo_request(), indent=2)
    with st.form("ops_generate"):
        source = st.text_area("Handoff JSON", key="ops_input", height=200)
        generate = st.form_submit_button("Generate execution plan")
    if generate:
        # Clear selected view on every attempt; don't show old success as new output.
        st.session_state.pop("ops_active", None)
        try:
            request = json.loads(source)
            result = agent.generate_execution_plan(request)
        except (ValueError, TypeError):
            result = {"status": "needs_input", "message": "Enter valid JSON handoff data."}
        st.session_state.ops_message = result
        if result["status"] == "success":
            plan = result["data"]["execution_plan"]
            st.session_state.ops_active = (plan["event_id"], plan["proposal_id"])
    msg = st.session_state.get("ops_message")
    if msg:
        (st.success if msg["status"] == "success" else st.warning)(msg["status"] + ": " + msg["message"])
    if "ops_active" not in st.session_state:
        return
    event_id, proposal_id = st.session_state.ops_active
    base = {"event_id": event_id, "proposal_id": proposal_id}
    data = agent.handle({**base, "action": "monitor_execution"})["data"]
    plan, summary, bookings = data["execution_plan"], data["summary"], data["bookings"]
    st.subheader("2. Execution overview")
    st.caption(f"Event: {event_id} · Proposal: {proposal_id}")
    cols = st.columns(3)
    cols[0].metric("Tasks", summary["total"])
    cols[1].metric("Completed", summary["completed"])
    cols[2].metric("Delayed", summary["delayed"])
    st.progress(summary["completed"] / summary["total"] if summary["total"] else 0)
    if summary["execution_complete"]:
        st.success("All execution tasks completed; every confirmed booking has an assigned task.")
    if summary["unassigned_booking_ids"]:
        st.warning("Some confirmed bookings have no task. Assign them explicitly below.")
    st.dataframe(plan["tasks"], hide_index=True, width="stretch")
    with st.expander("Confirmed vendor bookings", expanded=True):
        st.dataframe([{k: b[k] for k in ("booking_id", "vendor_id", "service_type", "status", "mock")}
                      for b in bookings], hide_index=True, width="stretch")
    task_labels = {t["task_id"]: t["title"] + " · " + t["status"] for t in plan["tasks"]}
    booking_labels = {None: "Internal task / no vendor", **{
        b["booking_id"]: b["service_type"] + " · " + b["vendor_id"] + " · " + b["booking_id"] for b in bookings}}

    def execute(payload):
        st.session_state.ops_message = agent.handle({**base, **payload})
        st.rerun()

    st.subheader("3. Assign and update tasks")
    with st.form("ops_assignment"):
        task = st.selectbox("Task to assign", list(task_labels), format_func=task_labels.get, key="ops_assign_task")
        booking = st.selectbox("Confirmed booking", list(booking_labels), format_func=booking_labels.get, key="ops_booking")
        if st.form_submit_button("Save assignment"):
            execute({"action": "assign_task", "task_id": task, "booking_id": booking})
    with st.form("ops_progress"):
        task = st.selectbox("Task to update", list(task_labels), format_func=task_labels.get, key="ops_update_task")
        status = st.selectbox("New status", TASK_STATUSES, key="ops_status")
        reason = st.text_input("Delay reason (required for DELAYED)", key="ops_reason")
        if st.form_submit_button("Update task status"):
            execute({"action": "update_task_status", "task_id": task, "status": status, "reason": reason})
    with st.expander("Add an operational task (arrival, setup or pack-down)"):
        with st.form("ops_add"):
            title = st.text_input("Task title", key="ops_title")
            start = st.text_input("Start (ISO 8601 with timezone)", placeholder="2026-12-05T16:00:00+11:00", key="ops_start")
            end = st.text_input("End (ISO 8601 with timezone)", placeholder="2026-12-05T17:00:00+11:00", key="ops_end")
            booking = st.selectbox("Booking for new task", list(booking_labels), format_func=booking_labels.get, key="ops_add_booking")
            if st.form_submit_button("Add task"):
                execute({"action": "add_task", "title": title, "start_at": start, "end_at": end, "booking_id": booking})
    st.download_button("Download current Operations result", json.dumps(
        agent.handle({**base, "action": "monitor_execution"}), indent=2),
        file_name="operations-result.json", mime="application/json")


if __name__ == "__main__":
    st.set_page_config(page_title="Event Operations", page_icon="📋", layout="wide")
    render_operations()
