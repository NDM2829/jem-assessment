from datetime import date
from io import BytesIO

from jem.pipeline import ingest, ingest_demo


def bundle(**changes):
    files = {
        "employees.csv": b"employee_id,full_name,primary_site_id,contract_ordinary_hours\n001,One,S1,45\n",
        "sites.csv": b"site_id,site_name\nS1,Site\n",
        "shifts.csv": b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nA,001,S1,2026-08-10,08:00,17:00\nB,001,S1,2026-08-12,08:00,\n",
        "shift_notes.csv": b"shift_id,note\nA,n/a\nB,\nZ,unmatched\n",
    }
    files.update(changes)
    return files


def test_demo_counts_and_reporting_week():
    result = ingest_demo(".")
    assert result.accepted
    assert result.bundle.row_counts["employees.csv"] == 213
    assert result.bundle.row_counts["shifts.csv"] == 8863
    assert result.reporting.week_start == date(2026, 8, 10)
    assert result.reporting.last_shift_date == date(2026, 8, 12)
    assert result.reporting.mode == "wednesday_snapshot"
    assert any(issue.issue == "Missing clock-out" for issue in result.issues)


def test_duplicate_joins_and_unmatched_notes_remain_safe():
    data = bundle(**{
        "sites.csv": b"site_id,site_name\nS1,Original\nS1,Conflict\nS2,Valid\n",
        "shifts.csv": b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nA,001,S1,2026-08-10,08:00,17:00\nA,001,S2,2026-08-10,08:00,17:00\nB,001,S2,2026-08-12,08:00,17:00\n",
    })
    result = ingest(data)
    assert result.accepted
    assert "S1" not in result.sites_by_id
    assert "A" not in result.shifts_by_id
    assert result.note_links == (None, "B", None)
    assert set(result.notes_by_shift) == {"B"}
    assert len(result.notes) == 3


def test_missing_required_column_rejects_bundle_without_traceback():
    result = ingest(bundle(**{"employees.csv": b"full_name,primary_site_id\nOne,S1\n"}))
    assert not result.accepted
    assert any(issue.file == "employees.csv" and "Missing required columns" in issue.issue and issue.severity == "error" for issue in result.issues)


def test_preserves_na_and_blanks_in_note_text():
    result = ingest(bundle())
    assert [row["note"] for row in result.notes] == ["n/a", "", "unmatched"]
    assert result.employees_by_id["001"]["employee_id"] == "001"
    assert result.accepted


def test_replacement_does_not_reuse_previous_register_or_results():
    old = ingest(bundle())
    replacement = bundle(**{
        "employees.csv": b"employee_id,full_name,primary_site_id,contract_ordinary_hours\n002,Two,S2,45\n",
        "sites.csv": b"site_id,site_name\nS2,Other\n",
        "shifts.csv": b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nC,002,S2,2026-08-19,08:00,17:00\n",
        "shift_notes.csv": b"shift_id,note\nC,new\n",
    })
    new = ingest(replacement)
    assert old.reporting.week_start == date(2026, 8, 10)
    assert new.reporting.week_start == date(2026, 8, 17)
    assert set(new.employees_by_id) == {"002"}
    assert set(new.sites_by_id) == {"S2"}
    assert [row["note"] for row in new.notes] == ["new"]
    rejected = ingest({"shifts.csv": replacement["shifts.csv"]})
    assert not rejected.accepted
    assert rejected.employees_by_id == {}
    assert rejected.sites_by_id == {}


def test_explicit_replay_and_early_coverage_states():
    data = bundle(**{"shifts.csv": b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nA,001,S1,2026-08-10,08:00,17:00\nB,001,S1,2026-08-12,08:00,17:00\nC,001,S1,2026-08-17,08:00,17:00\n"})
    assert ingest(data, as_of="2026-08-12").reporting.mode == "historical_replay"
    assert ingest(data, as_of="2026-08-10").reporting.mode == "before_wednesday"


def test_payroll_contents_are_never_retained_or_reported():
    result = ingest(bundle(**{"payroll_details.csv": b"bank_name,account_number\nsecret-bank,secret-account\n"}))
    assert result.accepted
    assert "payroll_details.csv" not in result.bundle.tables
    assert "secret-account" not in str(result)


def test_optional_missing_or_malformed_files_do_not_block_core_ingestion():
    result = ingest(bundle(**{"shift_notes.csv": b"shift_id,wrong_header\nA,n/a\n"}))
    assert result.accepted
    assert any("Note classification unavailable" in message for message in result.unavailable_outputs)
    assert not any(issue.file == "payroll_details.csv" for issue in result.issues)


def test_browser_style_file_objects_use_same_loader():
    files = {name: BytesIO(contents) for name, contents in bundle().items()}
    result = ingest(files)
    assert result.accepted
    assert result.bundle.row_counts["shifts.csv"] == 2
    assert [row["note"] for row in result.notes] == ["n/a", "", "unmatched"]
