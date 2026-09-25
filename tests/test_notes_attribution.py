import csv
from datetime import date, timedelta
import io
from math import isclose
from pathlib import Path

from jem.attribution import allocate_overtime
from jem.features import source_shifts
from jem.hours import parse_shift
from jem.note_evaluation import evaluate_review
from jem.notes import CATEGORIES, classify_note, note_classifications_csv_bytes, note_evidence_csv_bytes
from jem.pipeline import ingest_demo
from jem.notes import classify_bundle
from jem.workflow import employee_note_rows, load_policy, process_bundle


ROOT = Path(__file__).parents[1]


def test_reference_corrections_and_original_text():
    cases = (
        ("Centre manager requested additional cover for stocktake", "unclear_or_mixed", False, "not_stated"),
        ("Client asked us to stay for the delivery, ok'd by centre mgmt", "client_requested", True, "confirmed_in_note"),
        ("Client signed for the extra hours but real reason is relief no show", "relief_problem", False, "confirmed_in_note"),
        ("Stood in for Sibiya", "cover_unspecified", False, "not_stated"),
        ("", "no_useful_information", False, "not_stated"),
        ("n/a", "no_useful_information", False, "not_stated"),
    )
    rows = tuple(classify_note(text, shift_id=f"S{i}") for i, (text, _, _, _) in enumerate(cases))
    for item, (text, category, client, approval) in zip(rows, cases):
        assert (item.note, item.category, item.explicit_client_request, item.approval_status) == (text, category, client, approval)
        assert item.category in CATEGORIES
    exported = list(csv.DictReader(io.StringIO(note_classifications_csv_bytes(rows).decode())))
    assert list(exported[0]) == ["shift_id", "category", "note"]
    assert [row["note"] for row in exported] == [case[0] for case in cases]
    evidence = list(csv.DictReader(io.StringIO(note_evidence_csv_bytes(rows).decode())))
    assert [row["note"] for row in evidence] == [case[0] for case in cases]
    assert all(row["rules_version"] == "notes-1.0" for row in evidence)
    assert {"normalised_note", "matched_evidence", "approval_status", "needs_review"} <= set(evidence[0])
    assert rows[0].cause_pile == "unknown"
    assert rows[2].cause_pile == "operational_associated"


def test_multilingual_unknown_and_typo_evidence():
    unfamiliar = classify_note("未知原因")
    assert unfamiliar.category == "unclear_or_mixed" and unfamiliar.needs_review
    typo = classify_note("relief never arriived, stayed on till 6am")
    assert typo.category == "relief_problem"
    assert typo.typo_corrections and typo.needs_review
    mixed = classify_note("Client requested extra cover; relief never arrived")
    assert mixed.category == "unclear_or_mixed" and mixed.cause_pile == "unknown"


def test_duplicate_notes_do_not_duplicate_hours_and_conflict_is_unknown():
    monday = date(2026, 8, 3)
    shifts = tuple(parse_shift({"shift_id": f"S{day}", "employee_id": "E1",
                                "site_id": "SITE2" if day == 6 else "SITE1",
                                "shift_date": (monday + timedelta(days=day)).isoformat(),
                                "clock_in_time": "08:00", "clock_out_time": "18:00"})
                   for day in range(7))
    notes = (classify_note("Client asked us to stay", shift_id="S5", linked_shift_id="S5"),
             classify_note("Client asked us to stay", shift_id="S5", linked_shift_id="S5"),
             classify_note("Client asked for delivery", shift_id="S6", linked_shift_id="S6"),
             classify_note("Relief never arrived", shift_id="S6", linked_shift_id="S6"))
    report = allocate_overtime(shifts, {"E1": {}}, {"SITE1": {"site_name": "One"},
                                                       "SITE2": {"site_name": "Two"}},
                               monday + timedelta(days=7), notes)
    assert report.eligible_employee_weeks == 1
    assert len(report.allocations) == 7
    assert isclose(report.total_overtime_hours, 25.0)
    assert report.pile_hours == {"client_requested": 10.0, "operational_associated": 0,
                                 "unknown": 15.0}
    assert report.allocations[5].note_count == 2
    assert report.allocations[6].category == "unclear_or_mixed"
    assert {site.site_id: site.total_overtime_hours for site in report.site_summaries} == {
        "SITE1": 15.0, "SITE2": 10.0}
    assert isclose(sum(row.proportional_overtime_hours for row in report.allocations), 25.0)
    assert len(list(csv.DictReader(io.StringIO(note_classifications_csv_bytes(notes).decode())))) == 4


def test_missing_duration_week_is_excluded_from_overtime_association():
    monday = date(2026, 8, 3)
    shifts = tuple(parse_shift({"shift_id": f"S{day}", "employee_id": "E1", "site_id": "SITE1",
                                "shift_date": (monday + timedelta(days=day)).isoformat(),
                                "clock_in_time": "08:00", "clock_out_time": "" if day == 6 else "18:00"})
                   for day in range(7))
    report = allocate_overtime(shifts, {"E1": {}}, {"SITE1": {"site_name": "One"}},
                               monday + timedelta(days=7), ())
    assert report.eligible_employee_weeks == 0
    assert report.excluded_employee_weeks == 1
    assert report.exclusion_reasons["missing_clockout"] == 1
    assert report.total_overtime_hours == 0


def test_full_demo_export_preserves_source_order_and_reconciles():
    result = ingest_demo(ROOT)
    classified = classify_bundle(result)
    rows = list(csv.DictReader(io.StringIO(note_classifications_csv_bytes(classified).decode())))
    assert len(rows) == len(result.notes) == 2117
    assert [(row["shift_id"], row["note"]) for row in rows] == [
        (row["shift_id"], row["note"]) for row in result.notes]
    report = allocate_overtime(source_shifts(result), result.employees_by_id, result.sites_by_id,
                               result.reporting.week_start, classified)
    assert (report.eligible_employee_weeks, report.excluded_employee_weeks) == (1666, 251)
    assert isclose(report.total_overtime_hours, 2364.5)
    assert isclose(report.pile_hours["operational_associated"], 319.5)
    assert isclose(report.pile_hours["client_requested"], 80.5)
    assert isclose(report.pile_hours["unknown"], 1964.5)


def test_review_metrics_pending_then_match_only_exact_source_text():
    items = (classify_note("n/a", shift_id="S1"), classify_note("Relief never arrived", shift_id="S2"))
    header = "sample_id,sample_split,shift_id,note,human_category,reviewer,review_comment\n"
    blank = (header + "N1,random_validation,S1,n/a,,,\nN2,targeted_challenge,S2,Relief never arrived,,,\n").encode()
    pending = evaluate_review(blank, items)
    assert pending["status"] == "pending"
    assert pending["splits"]["random_validation"]["accuracy"] is None
    reviewed = (header + "N1,random_validation,S1,n/a,no_useful_information,Human,\n"
                "N2,targeted_challenge,S2,Changed text,relief_problem,Human,\n").encode()
    report = evaluate_review(reviewed, items)
    assert report["splits"]["random_validation"]["matched_reviewed"] == 1
    assert report["splits"]["targeted_challenge"]["stale_or_ambiguous"] == 1
    assert report["splits"]["targeted_challenge"]["accuracy"] is None
    assert report["splits"]["random_validation"]["cause_pile_confusion"]["rows"][2][2] == 1


def test_employee_details_use_only_uniquely_linked_current_notes():
    processed = process_bundle(ingest_demo(ROOT), load_policy(ROOT / "config" / "prediction_policy.toml"))
    week = processed.ingestion.reporting.week_start
    shift_lookup = {shift.shift_id: shift for shift in processed.shifts}
    note = next(row for row in processed.note_classifications
                if row.linked_shift_id and (shift := shift_lookup[row.linked_shift_id]).shift_date
                and week <= shift.shift_date < week + timedelta(days=3))
    employee = shift_lookup[note.linked_shift_id].employee_id
    assert any(row["Shift ID"] == note.shift_id and row["Note"] == note.note
               and row["Category"] == note.category for row in employee_note_rows(processed, employee))
