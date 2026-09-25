from dataclasses import replace
from datetime import date
from pathlib import Path
from shutil import copyfile

from streamlit.testing.v1 import AppTest

from jem.io import FILES, demo_sources
from jem.pipeline import ingest
from jem.workflow import input_fingerprint, load_policy, process_bundle, source_fingerprint


ROOT = Path(__file__).parents[1]


def test_input_fingerprint_tracks_source_asof_and_policy(monkeypatch):
    sources = demo_sources(ROOT)
    policy = load_policy(ROOT / "config" / "prediction_policy.toml")
    baseline = input_fingerprint(sources, date(2026, 8, 12), policy)
    assert source_fingerprint(sources) == source_fingerprint(dict(sources))
    assert baseline != input_fingerprint(sources, date(2026, 8, 5), policy)
    assert baseline != input_fingerprint(sources, date(2026, 8, 12), replace(policy, digest="changed"))
    changed = dict(sources)
    changed["shift_notes.csv"] = b"shift_id,note\nA,replacement\n"
    assert baseline != input_fingerprint(changed, date(2026, 8, 12), policy)
    monkeypatch.setattr("jem.workflow.RULES_VERSION", "future-note-rules")
    assert baseline != input_fingerprint(sources, date(2026, 8, 12), policy)


def test_bundled_demo_processes_without_unused_payroll_file(tmp_path):
    demo_dir = tmp_path / "data" / "demo"
    demo_dir.mkdir(parents=True)
    for name in FILES:
        if name != "payroll_details.csv":
            copyfile(ROOT / "data" / "demo" / name, demo_dir / name)
    sources = demo_sources(tmp_path)
    assert "payroll_details.csv" not in sources
    ingestion = ingest(sources)
    assert ingestion.accepted
    assert not any(issue.file == "payroll_details.csv" for issue in ingestion.issues)
    processed = process_bundle(ingestion, load_policy(ROOT / "config" / "prediction_policy.toml"))
    assert len(processed.queue) == 213
    assert processed.predictions_csv == (ROOT / "predictions.csv").read_bytes()
    copyfile(ROOT / "app.py", tmp_path / "app.py")
    (tmp_path / "config").mkdir()
    copyfile(ROOT / "config" / "prediction_policy.toml", tmp_path / "config" / "prediction_policy.toml")
    app = AppTest.from_file(tmp_path / "app.py").run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "39"


def test_manager_lists_and_periods_keep_all_employees_and_evidence():
    from jem.workflow import (attribution_summary, current_note_rows, employee_actions,
                              filter_queue, operational_actions)

    processed = process_bundle(ingest(demo_sources(ROOT)), load_policy(ROOT / "config" / "prediction_policy.toml"))
    alerts = filter_queue(processed, status="Breach alerts")
    reviews = filter_queue(processed, status="Records to check")
    assert len(alerts) == 39 and all(row.forecast.will_breach for row in alerts)
    assert len(reviews) == 28 and all(row.needs_review for row in reviews)
    assert len(filter_queue(processed)) == 213
    assert len({row.employee_id for row in alerts} & {row.employee_id for row in reviews}) == 10
    assert [row.employee_id for row in filter_queue(processed, search=" e1001 ")] == ["E1001"]
    assert not filter_queue(processed, search="not an employee")
    week = processed.ingestion.reporting.week_start
    current = operational_actions(processed)
    historical = operational_actions(processed, historical=True)
    assert len(current) == 26 and len(historical) == 51
    assert all(action.period_start >= week for action in current)
    assert all(action.period_start < week for action in historical)
    assert not set(current) & set(historical)
    shifts = {row.shift_id: row for row in processed.shifts}
    from datetime import timedelta
    assert all(week <= shifts[row["Shift ID"]].shift_date <= week + timedelta(days=2)
               for row in current_note_rows(processed))
    suspect = employee_actions(processed, "E1099")
    assert suspect[0].kind == "overlap"
    assert any(action.kind == "breach_alert" for action in suspect)
    summary = attribution_summary(processed)
    assert sum(row["Hours"] for row in summary["rows"]) == processed.attribution.total_overtime_hours
    assert summary["end"] < week
    assert summary["sites"][0].site_name == "Menlyn Park Centre"
