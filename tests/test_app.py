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
        ("shift_notes.csv", f"shift_id,note\nQ1,{employees[0]} replacement note\n".encode(), "text/csv"),
    ]


def test_demo_views_filter_and_selection_reuse_result():
    app = AppTest.from_file(ROOT / "app.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "Act today"
    assert [(item.label, item.value) for item in app.metric] == [
        ("Breach alerts", "39"), ("Records to check", "28")]
    original = app.session_state["active_result"]
    assert original.predictions_csv == (ROOT / "predictions.csv").read_bytes()
    assert any("213 employees assessed · 10 in both groups" in item.value for item in app.caption)
    assert len(app.dataframe[0].value) == 39
    assert "Do today" in app.dataframe[0].value.columns
    assert not any(box.label == "Page" for box in app.selectbox)
    app.session_state["employee_table"] = {"selection": {"rows": [0]}}
    app.run(timeout=30)
    assert app.session_state["active_result"] is original
    assert any("Do today" in item.value for item in app.markdown)
    assert any("Hours and shifts" in item.label for item in app.expander)
    app.button[0].click().run(timeout=30)
    assert len(app.dataframe[0].value) == 39  # Back does not reopen the selected row.
    app.radio(key="queue_status").set_value("Records to check").run(timeout=30)
    assert len(app.dataframe[0].value) == 28
    assert app.dataframe[0].value["What to check"].str.len().gt(0).all()
    assert "Confirm overlapping shifts" in app.dataframe[0].value.iloc[0]["What to check"]
    app.radio(key="queue_status").set_value("All employees").run(timeout=30)
    assert len(app.dataframe[0].value) == 213
    assert "Breach alert" in app.dataframe[0].value.columns
    app.text_input(key="employee_search").set_value("E1001").run(timeout=30)
    assert len(app.dataframe[0].value) == 1
    app.session_state["employee_table"] = {"selection": {"rows": [0]}}
    app.run(timeout=30)
    assert app.session_state["selected_employee"] == "E1001"
    app.button[0].click().run(timeout=30)
    assert len(app.dataframe[0].value) == 1
    app.text_input(key="employee_search").set_value("no such employee").run(timeout=30)
    assert any("No employees match" in item.value for item in app.info)
    app.text_input(key="employee_search").set_value("").run(timeout=30)
    app.selectbox(key="site_filter").set_value(app.selectbox(key="site_filter").options[1]).run(timeout=30)
    assert not app.exception
    assert app.session_state["active_result"] is original
    app.radio(key="view").set_value("Why overtime").run(timeout=30)
    assert not app.exception
    assert original.note_classifications_csv == (ROOT / "note_classifications.csv").read_bytes()
    assert any("83.1% of overtime" in item.value for item in app.markdown)
    assert any("Random sample: 93% agreement" in item.value for item in app.markdown)
    assert any("Separate challenge sample: 90% agreement" in item.value for item in app.markdown)
    assert any(item.label == "Earlier relief patterns" for item in app.expander)
    assert app.session_state["active_result"] is original
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    assert app.title[0].value == "Load new data"
    assert len(app.date_input) == 1
    assert not app.exception


def test_upload_replacement_and_failure_clear_old_results():
    app = AppTest.from_file(ROOT / "app.py").run(timeout=30)
    app.selectbox(key="site_filter").set_value(app.selectbox(key="site_filter").options[1]).run(timeout=30)
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    app.radio(key="source_mode").set_value("Replacement upload").run(timeout=30)
    assert app.session_state["active_result"] is None
    first = replacement_files(date(2026, 9, 7), ("A1", "A2"))
    app.get("file_uploader")[0].set_value(first).run(timeout=30)
    app.button(key="process_bundle").click().run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "Act today"  # Successful load navigates automatically.
    assert app.selectbox(key="site_filter").value == "All sites"
    assert app.session_state["active_result"].ingestion.reporting.week_start == date(2026, 9, 7)
    assert len(app.session_state["active_result"].queue) == 2
    assert b"A1 replacement note" in app.session_state["active_result"].note_classifications_csv
    first_predictions_csv = app.session_state["active_result"].predictions_csv
    first_notes_csv = app.session_state["active_result"].note_classifications_csv
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    assert app.session_state["active_result"] is not None  # Upload survives navigation.
    app.date_input[0].set_value(date(2026, 9, 2)).run(timeout=30)
    assert app.session_state["active_result"] is None
    app.button(key="process_bundle").click().run(timeout=30)
    assert app.session_state["active_result"].ingestion.reporting.week_start == date(2026, 8, 31)
    assert set(row.employee_id for row in app.session_state["active_result"].queue) == {"A1", "A2"}
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    second = replacement_files(date(2026, 9, 14), ("B1", "B2"))
    app.get("file_uploader")[0].set_value(second).run(timeout=30)
    assert app.session_state["active_result"] is None
    assert any("Choose another export" in item.value for item in app.error)
    app.button(key="new_upload").click().run(timeout=30)
    app.get("file_uploader")[0].set_value([second[2]]).run(timeout=30)
    assert app.session_state["active_result"] is None
    assert app.button(key="process_bundle").disabled
    app.radio(key="view").set_value("Act today").run(timeout=30)
    assert any("No predictions are active" in item.value for item in app.warning)
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    app.button(key="new_upload").click().run(timeout=30)
    app.get("file_uploader")[0].set_value(second).run(timeout=30)
    app.button(key="process_bundle").click().run(timeout=30)
    assert not app.exception
    result = app.session_state["active_result"]
    assert result.ingestion.reporting.week_start == date(2026, 9, 14)
    assert set(row.employee_id for row in result.queue) == {"B1", "B2"}
    assert b"A1" not in result.predictions_csv and b"B1" in result.predictions_csv
    assert b"B1 replacement note" in result.note_classifications_csv
    assert b"A1 replacement note" not in result.note_classifications_csv
    assert len(result.note_classifications) == 1
    assert result.predictions_csv != first_predictions_csv
    assert result.note_classifications_csv != first_notes_csv
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    app.button(key="new_upload").click().run(timeout=30)
    app.get("file_uploader")[0].set_value(second).run(timeout=30)
    app.get("file_uploader")[0].set_value([]).run(timeout=30)
    assert app.session_state["active_result"] is None
    assert not app.session_state["uploaded_sources"]


def test_upload_without_notes_explains_missing_requirement():
    app = AppTest.from_file(ROOT / "app.py").run(timeout=30)
    app.radio(key="view").set_value("Load new data").run(timeout=30)
    app.radio(key="source_mode").set_value("Replacement upload").run(timeout=30)
    files = replacement_files(date(2026, 9, 7), ("A1", "A2"))[:3]
    app.get("file_uploader")[0].set_value(files).run(timeout=30)
    assert any("why overtime happened is unavailable" in item.value for item in app.warning)
    app.button(key="process_bundle").click().run(timeout=30)
    assert not app.exception
    app.radio(key="view").set_value("Why overtime").run(timeout=30)
    assert any("why overtime happened is unavailable" in item.value for item in app.warning)
