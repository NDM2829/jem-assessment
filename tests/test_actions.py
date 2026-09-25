from datetime import date, timedelta
import json
from pathlib import Path

from jem.actions import REVIEW_KINDS, build_actions
from jem.features import build_snapshot, source_shifts
from jem.notes import classify_bundle
from jem.pipeline import ingest
from jem.predictors.base import Forecast
from scripts.export_assessment import export_assessment


ROOT = Path(__file__).parents[1]


def _bundle():
    monday = date(2026, 8, 10)
    shifts = ["shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time"]
    for key, offset, start, end in (
        ("R1", -7, "08:00", "16:00"), ("R2", -6, "08:00", "16:00"),
        ("M", 0, "08:00", ""), ("O1", 1, "08:00", "16:00"),
        ("O2", 1, "12:00", "18:00"), ("E", 2, "08:00", "12:00"),
        ("C", 2, "12:00", "18:00"), ("G", 2, "18:00", "20:00")):
        shifts.append(f"{key},E,S,{monday + timedelta(days=offset)},{start},{end}")
    shifts.append("U,E,S,invalid,08:00,16:00")
    notes = "shift_id,note\nR1,Relief did not arrive\nR1,Relief did not arrive\nR2,Relief was late\nE,Machine broke down\nC,Client asked us to stay for delivery; approved by centre manager\nG,Centre manager requested additional cover for stocktake\nX,unmatched note\n"
    return {
        "employees.csv": b"employee_id,full_name,primary_site_id,contract_ordinary_hours,role,shift_pattern\nE,Employee E,S,45,Guard,Day\nN,Employee N,S,45,Guard,Day\n",
        "sites.csv": b"site_id,site_name\nS,Site S\n",
        "shifts.csv": ("\n".join(shifts) + "\n").encode(),
        "shift_notes.csv": notes.encode(),
    }


def test_actions_trace_quality_and_note_rules_without_inventing_allowance():
    ingestion = ingest(_bundle())
    assert ingestion.accepted
    shifts = source_shifts(ingestion)
    snapshots = build_snapshot(shifts, ingestion.employees_by_id, ingestion.reporting.week_start)
    forecasts = tuple(Forecast(row.employee_id, True, 0.2, row.week_start,
                      row.week_start + timedelta(days=6), 0.05, "correlated-hours-1.0",
                      "test-support", None, {}) for row in snapshots)
    actions = build_actions(ingestion, shifts, snapshots, forecasts, classify_bundle(ingestion))
    kinds = [action.kind for action in actions]
    assert kinds.count("relief_pattern") == 1
    relief = next(action for action in actions if action.kind == "relief_pattern")
    assert relief.site_id == "S" and relief.period_start == date(2026, 8, 3)
    assert {source.key for source in relief.sources if source.file == "shifts.csv"} == {"R1", "R2"}
    assert len([source for source in relief.sources if source.file == "shifts.csv"]) == 2
    assert any(action.kind == "missing_clockout" and action.sources[0].key == "M"
               and action.sources[0].shift_date == date(2026, 8, 10) for action in actions)
    assert any(action.kind == "overlap" and {source.key for source in action.sources} == {"O1", "O2"}
               for action in actions)
    equipment = next(action for action in actions if action.kind == "equipment_note")
    assert "Machine broke down" in equipment.reason
    client = next(action for action in actions if action.kind == "client_scope")
    assert "Client asked us to stay" in client.reason and "approved" in client.reason
    assert not any(action.kind == "client_scope" and any(source.key == "G" for source in action.sources)
                   for action in actions)
    assert all(action.remaining_hours_before_55 is None for action in actions if action.kind == "breach_alert")
    assert any(action.kind == "no_current_records" and action.employee_id == "N" for action in actions)
    assert any(action.kind == "unmatched_note" and action.sources[0].key == "X" for action in actions)
    assert any(action.kind == "invalid_shift" and action.sources[0].key == "U" for action in actions)
    assert all(action.sources for action in actions)
    assert any(action.kind in REVIEW_KINDS for action in actions)


def test_usable_recorded_hours_allow_numeric_allowance():
    bundle = _bundle()
    bundle["shifts.csv"] = b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nA,E,S,2026-08-03,08:00,16:00\nB,E,S,2026-08-10,08:00,16:00\nC,E,S,2026-08-12,08:00,17:00\n"
    bundle["shift_notes.csv"] = b"shift_id,note\n"
    ingestion = ingest(bundle)
    shifts = source_shifts(ingestion)
    snapshots = build_snapshot(shifts, ingestion.employees_by_id, ingestion.reporting.week_start)
    forecasts = tuple(Forecast(row.employee_id, True, 0.2, row.week_start,
                      row.week_start + timedelta(days=6), 0.05, "correlated-hours-1.0",
                      "test-support", None, {}) for row in snapshots)
    actions = build_actions(ingestion, shifts, snapshots, forecasts, ())
    e = next(action for action in actions if action.kind == "breach_alert" and action.employee_id == "E")
    n = next(action for action in actions if action.kind == "breach_alert" and action.employee_id == "N")
    assert e.recorded_hours == 17 and e.remaining_hours_before_55 == 38
    assert n.remaining_hours_before_55 is None


def test_shared_export_produces_both_original_outputs(tmp_path):
    employees, notes = export_assessment(ROOT / "data" / "demo", tmp_path)
    assert employees == 213 and notes == 2117
    assert (tmp_path / "predictions.csv").read_bytes() == (ROOT / "predictions.csv").read_bytes()
    assert (tmp_path / "note_classifications.csv").read_bytes() == (ROOT / "note_classifications.csv").read_bytes()
    manifest = json.loads((tmp_path / "predictions_manifest.json").read_text())
    assert "payroll_details.csv" not in manifest["input_sha256"]
