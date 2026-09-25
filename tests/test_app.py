from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).parents[1]


def replacement_files(current_monday: date, employees: tuple[str, str]):
    employee_csv = "employee_id,full_name,primary_site_id,contract_ordinary_hours,role,shift_pattern\n"
    employee_csv += "".join(f"{identifier},Person {identifier},S1,45,Guard,Day\n" for identifier in employees)
    shifts = ["shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time"]
    serial = 0
    for week_offset in (-4, -3, -2, -1, 0):
        days = 3 if week_offset == 0 else 7
        for day_offset in range(days):
            day = current_monday + timedelta(days=7 * week_offset + day_offset)
            for employee in employees:
                serial += 1
                shifts.append(f"Q{serial},{employee},S1,{day},08:00,16:00")
    return [
        ("employees.csv", employee_csv.encode(), "text/csv"),
        ("sites.csv", b"site_id,site_name\nS1,Replacement Site\n", "text/csv"),
        ("shifts.csv", ("\n".join(shifts) + "\n").encode(), "text/csv"),
        ("shift_notes.csv", b"shift_id,note\nQ1,replacement note\n", "text/csv"),
    ]


def test_demo_views_filter_and_selection_reuse_result():
    app = AppTest.from_file(ROOT / "app.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "This week"
    assert [(item.label, item.value) for item in app.metric] == [
        ("Employees", "213"), ("Breach alerts", "39"), ("Data review", "28")]
    assert app.session_state["active_result"].predictions_csv == (ROOT / "predictions.csv").read_bytes()
    original = app.session_state["active_result"]
    app.selectbox[0].set_value(app.selectbox[0].options[1]).run(timeout=30)
    assert not app.exception
    assert app.session_state["active_result"] is original
    assert int(app.metric[0].value) < 213
    app.selectbox[1].set_value(app.selectbox[1].options[-1]).run(timeout=30)
    assert app.session_state["active_result"] is original
    assert any("Completed recorded hours" in item.value for item in app.markdown)
    app.sidebar.radio[0].set_value("Overtime reasons").run(timeout=30)
    assert "pending Step 6" in app.info[0].value
    app.sidebar.radio[0].set_value("Load data & checks").run(timeout=30)
    assert app.title[0].value == "Load data & checks"
    assert len(app.date_input) == 1
    assert not app.exception


def test_upload_replacement_and_failure_clear_old_results():
    app = AppTest.from_file(ROOT / "app.py").run(timeout=30)
    app.sidebar.radio[0].set_value("Load data & checks").run(timeout=30)
    app.sidebar.radio[1].set_value("Replacement upload").run(timeout=30)
    assert app.session_state["active_result"] is None
    first = replacement_files(date(2026, 9, 7), ("A1", "A2"))
    app.get("file_uploader")[0].set_value(first).run(timeout=30)
    assert app.button[1].label == "Process bundle"
    app.button[1].click().run(timeout=30)
    assert not app.exception
    assert app.session_state["active_result"].ingestion.reporting.week_start == date(2026, 9, 7)
    assert len(app.session_state["active_result"].queue) == 2
    app.date_input[0].set_value(date(2026, 9, 2)).run(timeout=30)
    assert app.session_state["active_result"] is None
    app.button[1].click().run(timeout=30)
    assert app.session_state["active_result"].ingestion.reporting.week_start == date(2026, 8, 31)
    app.sidebar.radio[0].set_value("This week").run(timeout=30)
    assert app.metric[0].value == "2"
    assert set(row.employee_id for row in app.session_state["active_result"].queue) == {"A1", "A2"}
    app.sidebar.radio[0].set_value("Load data & checks").run(timeout=30)
    second = replacement_files(date(2026, 9, 14), ("B1", "B2"))
    app.get("file_uploader")[0].set_value(second).run(timeout=30)
    assert app.session_state["active_result"] is None
    assert any("Start a new replacement upload" in item.value for item in app.error)
    app.button[0].click().run(timeout=30)
    app.get("file_uploader")[0].set_value([second[2]]).run(timeout=30)
    assert app.session_state["active_result"] is None
    app.sidebar.radio[0].set_value("This week").run(timeout=30)
    assert any("No predictions are active" in item.value for item in app.warning)
    app.sidebar.radio[0].set_value("Load data & checks").run(timeout=30)
    app.button[0].click().run(timeout=30)
    app.get("file_uploader")[0].set_value(second).run(timeout=30)
    app.button[1].click().run(timeout=30)
    assert not app.exception
    result = app.session_state["active_result"]
    assert result.ingestion.reporting.week_start == date(2026, 9, 14)
    assert set(row.employee_id for row in result.queue) == {"B1", "B2"}
    assert b"A1" not in result.predictions_csv
    assert b"B1" in result.predictions_csv
