from pathlib import Path
from streamlit.testing.v1 import AppTest

UI = Path(__file__).resolve().parents[2] / "ui/event_operations_ui.py"


def test_demo_and_invalid_replacement():
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    assert not app.exception
    app.button(key="ops_demo").click().run()
    app.button(key="FormSubmitter:ops_generate-Generate execution plan").click().run()
    assert not app.exception
    assert app.metric[0].value == "2"
    app.text_area(key="ops_input").set_value("not json")
    app.button(key="FormSubmitter:ops_generate-Generate execution plan").click().run()
    assert not app.exception and not app.metric
    assert "needs_input" in app.warning[0].value


def test_ui_progress_and_assignment():
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    app.button(key="ops_demo").click().run()
    app.button(key="FormSubmitter:ops_generate-Generate execution plan").click().run()
    booking_id = app.session_state.ops_service.monitor_execution("EV001", "P1")["bookings"][0]["booking_id"]
    app.selectbox(key="ops_booking").select(booking_id)
    app.button(key="FormSubmitter:ops_assignment-Save assignment").click().run()
    app.selectbox(key="ops_status").select("DELAYED")
    app.text_input(key="ops_reason").set_value("Vendor arriving late")
    app.button(key="FormSubmitter:ops_progress-Update task status").click().run()
    assert not app.exception
    assert app.metric[2].value == "1"
