"""Ingestion validation and reporting context; no hours or predictions yet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import BinaryIO, Mapping

from jem.io import Issue, LoadedBundle, RawTable, demo_sources, load_bundle


@dataclass(frozen=True)
class ReportingContext:
    week_start: date | None
    week_end: date | None
    as_of: date | None
    first_shift_date: date | None
    last_shift_date: date | None
    mode: str
    historical_state: str
    explanation: str


@dataclass(frozen=True)
class IngestionResult:
    bundle: LoadedBundle
    issues: tuple[Issue, ...]
    accepted: bool
    reporting: ReportingContext
    employees_by_id: dict[str, dict[str, str]]
    sites_by_id: dict[str, dict[str, str]]
    shifts_by_id: dict[str, dict[str, str]]
    notes: tuple[dict[str, str], ...]
    note_links: tuple[str | None, ...]
    notes_by_shift: dict[str, tuple[dict[str, str], ...]]
    unavailable_outputs: tuple[str, ...]


def _parse_date(value: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _valid_time(value: str) -> bool:
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return False
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def _valid_nonnegative(value: str) -> bool:
    try:
        number = float(value)
        return number >= 0 and number != float("inf")
    except ValueError:
        return False


def _unique_index(table: RawTable | None, filename: str, field: str, issues: list[Issue]) -> dict[str, dict[str, str]]:
    if table is None or field not in table.columns:
        return {}
    result: dict[str, dict[str, str]] = {}
    conflicted: set[str] = set()
    for row_number, row in enumerate(table.rows, start=2):
        key = row[field]
        if not key:
            issues.append(Issue(filename, row_number, None, "warning", "Blank " + field, "Supply a stable identifier for this row."))
        elif key in conflicted:
            issues.append(Issue(filename, row_number, key, "warning", "Repeated identifier remains ambiguous", "Resolve duplicate IDs in the source export."))
        elif key in result:
            issue = "Conflicting identifier" if result[key] != row else "Duplicate identifier"
            issues.append(Issue(filename, row_number, key, "warning", issue, "Keep one authoritative row for this identifier."))
            conflicted.add(key)
            del result[key]
        else:
            result[key] = row
    return result


def _reporting(shifts: RawTable | None, as_of: date | None, issues: list[Issue]) -> ReportingContext:
    dates = []
    if shifts and "shift_date" in shifts.columns:
        dates = [day for row in shifts.rows if (day := _parse_date(row["shift_date"])) is not None]
    if not dates:
        issues.append(Issue("shifts.csv", None, None, "error", "No valid shift start dates", "Provide shifts with ISO dates (YYYY-MM-DD)."))
        return ReportingContext(None, None, as_of, None, None, "unavailable", "unavailable", "Reporting week cannot be determined.")
    first, last = min(dates), max(dates)
    selected = as_of or last
    monday = selected - timedelta(days=selected.weekday())
    sunday = monday + timedelta(days=6)
    wednesday = monday + timedelta(days=2)
    if selected < first or selected > last or not any(monday <= d <= sunday for d in dates):
        issues.append(Issue("shifts.csv", None, None, "error", "Selected reporting week has no covered shift dates", "Choose an as-of date in a week present in this export."))
        mode = "unavailable"
        explanation = "Selected reporting week is outside shift-date coverage."
    elif selected < wednesday or last < wednesday:
        mode = "before_wednesday"
        explanation = "Export/selection ends before Wednesday; Wednesday forecast inputs are incomplete."
        issues.append(Issue("shifts.csv", None, None, "warning", "Wednesday reporting coverage incomplete", "Supply records through Wednesday or label this as an early partial snapshot."))
    elif last >= sunday and selected <= sunday:
        mode = "historical_replay"
        explanation = "Completed historical week selected for replay; use only records available by its Wednesday cutoff."
    elif last > sunday:
        mode = "historical_replay"
        explanation = "Historical week selected for replay; use only records available by its Wednesday cutoff."
    elif selected > wednesday:
        mode = "after_wednesday"
        explanation = "Selected date is after Wednesday; use the Wednesday cutoff for a comparable forecast."
    else:
        mode = "wednesday_snapshot"
        explanation = "Shift dates cover Wednesday of the selected Monday–Sunday reporting week."
    prior_sunday = monday - timedelta(days=1)
    prior_monday = monday - timedelta(days=7)
    if first <= prior_monday and last >= prior_sunday:
        historical = "prior_week_coverage_available"
    else:
        historical = "fallback_required"
        issues.append(Issue("shifts.csv", None, None, "warning", "No full prior Monday–Sunday date span", "Supply earlier historical shifts; later prediction code must expose its fallback state."))
    return ReportingContext(monday, sunday, selected, first, last, mode, historical, explanation)


def ingest(sources: Mapping[str, bytes | str | Path | BinaryIO], *, as_of: date | str | None = None) -> IngestionResult:
    """Validate a replacement bundle without mutating any prior result."""
    loaded = load_bundle(sources)
    issues = list(loaded.issues)
    if isinstance(as_of, str):
        parsed = _parse_date(as_of)
        if parsed is None:
            issues.append(Issue("shifts.csv", None, None, "error", "Invalid as-of date", "Use YYYY-MM-DD."))
        as_of = parsed
    employees = _unique_index(loaded.tables.get("employees.csv"), "employees.csv", "employee_id", issues)
    # Keep raw source intact, while removing unused identity numbers from the
    # processing lookup that later feature and display code will consume.
    employees = {key: {field: value for field, value in row.items() if field != "id_number"} for key, row in employees.items()}
    sites = _unique_index(loaded.tables.get("sites.csv"), "sites.csv", "site_id", issues)
    shifts = _unique_index(loaded.tables.get("shifts.csv"), "shifts.csv", "shift_id", issues)
    for filename, index in (("employees.csv", employees), ("sites.csv", sites), ("shifts.csv", shifts)):
        if filename in loaded.tables and not index:
            issues.append(Issue(filename, None, None, "error", "No unambiguous identifiers", "Correct or deduplicate IDs in this file."))
    for filename, table in loaded.tables.items():
        for row_number, row in enumerate(table.rows, start=2):
            def warn(message: str, correction: str, key: str | None = None) -> None:
                issues.append(Issue(filename, row_number, key, "warning", message, correction))
            if filename == "employees.csv":
                key = row.get("employee_id")
                site = row.get("primary_site_id", "")
                if site and site not in sites:
                    warn("Primary site does not resolve uniquely", "Correct site ID or site register.", key)
                hours = row.get("contract_ordinary_hours", "")
                if hours and not _valid_nonnegative(hours):
                    warn("Invalid contract ordinary hours", "Use a nonnegative finite number.", key)
            elif filename == "shifts.csv":
                key = row.get("shift_id")
                if row.get("employee_id") not in employees:
                    warn("Employee does not resolve uniquely", "Correct employee ID or employee register.", key)
                if row.get("site_id") not in sites:
                    warn("Site does not resolve uniquely", "Correct site ID or site register.", key)
                if not _parse_date(row.get("shift_date", "")):
                    warn("Invalid shift date", "Use YYYY-MM-DD.", key)
                if not _valid_time(row.get("clock_in_time", "")):
                    warn("Invalid clock-in time", "Use HH:MM in 24-hour time.", key)
                out = row.get("clock_out_time", "")
                if not out:
                    warn("Missing clock-out", "Confirm the end time; keep this row pending review.", key)
                elif not _valid_time(out):
                    warn("Invalid clock-out time", "Use HH:MM in 24-hour time.", key)
            elif filename == "public_holidays.csv" and not _parse_date(row.get("date", "")):
                warn("Invalid holiday date", "Use YYYY-MM-DD.")
            elif filename == "weekly_summary.csv":
                key = row.get("employee_id")
                day = _parse_date(row.get("week_starting", ""))
                if key not in employees:
                    warn("Employee does not resolve uniquely", "Correct employee ID or employee register.", key)
                if day is None or day.weekday() != 0:
                    warn("Invalid week starting date", "Use a Monday in YYYY-MM-DD format.", key)
                for field in ("total_hours", "overtime_hours"):
                    if not _valid_nonnegative(row.get(field, "")):
                        warn("Invalid " + field, "Use a nonnegative finite number.", key)
                if row.get("breached", "").strip().lower() not in {"true", "false", "0", "1", "yes", "no"}:
                    warn("Invalid breached value", "Use true/false, yes/no, or 1/0.", key)
    summary = loaded.tables.get("weekly_summary.csv")
    if summary and {"employee_id", "week_starting"}.issubset(summary.columns):
        seen: dict[tuple[str, str], dict[str, str]] = {}
        for row_number, row in enumerate(summary.rows, start=2):
            key = (row["employee_id"], row["week_starting"])
            if key in seen:
                kind = "Conflicting" if seen[key] != row else "Duplicate"
                issues.append(Issue("weekly_summary.csv", row_number, "|".join(key), "warning", kind + " employee-week summary", "Keep one authoritative summary per employee and week."))
            else:
                seen[key] = row
    notes = loaded.tables.get("shift_notes.csv")
    note_rows = notes.rows if notes else ()
    note_links = []
    grouped_notes: dict[str, list[dict[str, str]]] = {}
    for row_number, row in enumerate(note_rows, start=2):
        key = row.get("shift_id", "")
        shift = shifts.get(key)
        if shift and shift.get("employee_id") in employees and shift.get("site_id") in sites:
            note_links.append(key)
            grouped_notes.setdefault(key, []).append(row)
        else:
            note_links.append(None)
            issues.append(Issue("shift_notes.csv", row_number, key or None, "warning", "Note cannot be attributed to a unique shift", "Correct shift ID or keep note unassigned for classification."))
    reporting = _reporting(loaded.tables.get("shifts.csv"), as_of, issues)
    unavailable = []
    for name, output in (("shift_notes.csv", "Note classification"), ("public_holidays.csv", "Holiday context"), ("weekly_summary.csv", "Exported weekly summary comparison")):
        if name not in loaded.tables or not set(loaded.tables[name].columns).issuperset({"shift_id", "note"} if name == "shift_notes.csv" else {"date", "name"} if name == "public_holidays.csv" else {"employee_id", "week_starting", "total_hours", "overtime_hours", "breached"}):
            unavailable.append(output + " unavailable: " + name + " is missing or lacks required columns.")
    accepted = not any(issue.severity == "error" for issue in issues)
    return IngestionResult(loaded, tuple(issues), accepted, reporting, employees, sites, shifts, tuple(note_rows), tuple(note_links), {key: tuple(value) for key, value in grouped_notes.items()}, tuple(unavailable))


def ingest_demo(root: str | Path, *, as_of: date | str | None = None) -> IngestionResult:
    return ingest(demo_sources(root), as_of=as_of)
