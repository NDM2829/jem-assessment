"""Deterministic, source-linked manager actions; no scheduling or billing inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from jem.features import BREACH_HOURS, Snapshot
from jem.hours import Shift, find_overlaps, mask_after_cutoff
from jem.notes import NoteClassification
from jem.pipeline import IngestionResult
from jem.predictors.base import Forecast


@dataclass(frozen=True)
class SourceRecord:
    file: str
    row: int
    key: str
    shift_date: date | None = None


@dataclass(frozen=True)
class Action:
    kind: str
    recommendation: str
    reason: str
    sources: tuple[SourceRecord, ...]
    employee_id: str | None = None
    site_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    recorded_hours: float | None = None
    estimated_elapsed_hours: float | None = None
    estimated_carry_hours: float | None = None
    remaining_hours_before_55: float | None = None
    risk_score: float | None = None


REVIEW_KINDS = frozenset({"missing_clockout", "overlap", "invalid_shift", "cutoff_masked",
                          "no_current_records", "conflicting_notes", "unmatched_note"})
OPERATIONS_KINDS = frozenset({"relief_pattern", "equipment_note", "client_scope"})


def _usable_hours(snapshot: Snapshot) -> bool:
    """Allow a recorded-hours allowance only with complete usable current rows."""
    return bool(snapshot.records) and not any((snapshot.overlapping_records, snapshot.unknown_records,
        snapshot.missing_clockouts, snapshot.future_end_masked, snapshot.invalid_time_records,
        snapshot.excluded_shift_records, snapshot.undated_shift_records, snapshot.no_records))


def build_actions(ingestion: IngestionResult, shifts: tuple[Shift, ...],
                  snapshots: tuple[Snapshot, ...], forecasts: tuple[Forecast, ...],
                  notes: tuple[NoteClassification, ...]) -> tuple[Action, ...]:
    """Use the selected week's Wednesday snapshot and earlier note periods.

    Note patterns in completed earlier weeks are grouped by actual shift site.
    Selected-week notes and shift-quality actions stop at Wednesday's cutoff.
    """
    week = ingestion.reporting.week_start
    if not ingestion.accepted or week is None:
        raise ValueError("Actions require an accepted bundle and reporting week.")
    cutoff = datetime.combine(week + timedelta(days=3), time.min)
    shift_sources = tuple(SourceRecord("shifts.csv", index + 2, shift.shift_id, shift.shift_date)
                          for index, shift in enumerate(shifts))
    employee_sources = {row.get("employee_id", ""): SourceRecord("employees.csv", index + 2,
                        row.get("employee_id", "")) for index, row in
                        enumerate(ingestion.bundle.tables["employees.csv"].rows)
                        if row.get("employee_id", "") in ingestion.employees_by_id}
    unique_shift_sources = {shift.shift_id: shift_sources[index] for index, shift in enumerate(shifts)
                            if shift.shift_id in ingestion.shifts_by_id}
    unique_shifts = {shift.shift_id: shift for shift in shifts if shift.shift_id in ingestion.shifts_by_id}
    current = [(shift, source) for shift, source in zip(shifts, shift_sources)
               if shift.shift_date and week <= shift.shift_date < cutoff.date()]
    visible = [mask_after_cutoff(shift, cutoff) for shift in shifts
               if shift.shift_date and week - timedelta(days=1) <= shift.shift_date < cutoff.date()]
    actions: list[Action] = []

    for snapshot, forecast in zip(snapshots, forecasts):
        if snapshot.employee_id != forecast.employee_id:
            raise ValueError("Snapshot and forecast employee order differs.")
        employee_records = tuple(source for shift, source in current if shift.employee_id == snapshot.employee_id)
        if forecast.will_breach:
            usable = _usable_hours(snapshot)
            allowance = max(0.0, BREACH_HOURS - snapshot.known_hours) if usable else None
            reason = (f"{forecast.method_version} scored {forecast.risk_score:.1%} against its fixed "
                      f"{forecast.threshold:.1%} alert threshold; {snapshot.known_hours:.2f} recorded hours, "
                      f"{snapshot.imputed_elapsed:.2f} estimated elapsed hours and "
                      f"{snapshot.carry:.2f} estimated carry hours at Wednesday cutoff.")
            reason += (" Recorded shifts support an allowance to 55 hours, subject to export completeness."
                       if usable else " Records need confirmation before any numeric remaining-hours allowance.")
            if allowance is None:
                recommendation = "Confirm the flagged shift records before deciding how much more work to assign this week."
            elif snapshot.known_hours > BREACH_HOURS:
                recommendation = (f"Recorded hours already exceed 55 ({snapshot.known_hours:.2f} h). "
                                  "Confirm the total and review remaining assignments with the site supervisor today.")
            else:
                recommendation = (f"Check remaining assignments against the {allowance:.2f} h left before 55 "
                                  f"based on {snapshot.known_hours:.2f} recorded hours. "
                                  "Confirm the export is complete before using this allowance.")
            actions.append(Action("breach_alert", recommendation,
                                  reason, employee_records or (employee_sources[snapshot.employee_id],),
                                  employee_id=snapshot.employee_id, period_start=week, period_end=week + timedelta(days=6),
                                  recorded_hours=snapshot.known_hours, estimated_elapsed_hours=snapshot.imputed_elapsed,
                                  estimated_carry_hours=snapshot.carry, remaining_hours_before_55=allowance,
                                  risk_score=forecast.risk_score))
        if snapshot.no_records:
            actions.append(Action("no_current_records", "Confirm whether this employee has any shifts in the selected week.",
                                  "No dated shift appears through Wednesday; this does not establish zero hours or zero risk.",
                                  (employee_sources[snapshot.employee_id],), employee_id=snapshot.employee_id,
                                  period_start=week, period_end=week + timedelta(days=2)))

    for shift, source in current:
        if shift.missing_clockout:
            actions.append(Action("missing_clockout", f"Confirm the missing clock-out for shift {shift.shift_id} on {shift.shift_date}.",
                                  f"Shift {shift.shift_id} started on {shift.shift_date} and has a blank clock-out.",
                                  (source,), shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date,
                                  recorded_hours=shift.recorded_hours))
        if shift.invalid_time or shift.excluded_reason:
            actions.append(Action("invalid_shift", f"Correct or confirm the time or identifier for shift {shift.shift_id} on {shift.shift_date}.",
                                  f"Shift {shift.shift_id} on {shift.shift_date} has an invalid or ambiguous time/ID; its duration is not confirmed.",
                                  (source,), shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date))
        if shift.end_at and shift.end_at > cutoff and not shift.excluded_reason:
            actions.append(Action("cutoff_masked", f"Confirm the eventual clock-out for shift {shift.shift_id} ({shift.shift_date}); its end is beyond the Wednesday cutoff.",
                                  f"Shift {shift.shift_id} on {shift.shift_date} ends after Thursday 00:00 and was masked at the cutoff.",
                                  (source,), shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date))
    for shift, source in zip(shifts, shift_sources):
        if shift.shift_date is None:
            actions.append(Action("invalid_shift", f"Correct or confirm the date for shift {shift.shift_id} before relying on this employee's hours.",
                                  f"Shift {shift.shift_id} has no valid start date and cannot be assigned to a reporting week.",
                                  (source,), shift.employee_id, shift.site_id))

    for pair in find_overlaps(visible):
        left, right = unique_shift_sources.get(pair.shift_id_left), unique_shift_sources.get(pair.shift_id_right)
        if left is None or right is None or (left.shift_date < week and right.shift_date < week):
            continue
        actions.append(Action("overlap", f"Confirm overlapping shifts {left.key} and {right.key} before relying on their summed hours.",
                              f"Shift IDs {left.key} and {right.key} overlap by {pair.overlap_hours:.2f} hours; the recorded sum is suspect.",
                              (left, right), employee_id=pair.employee_id,
                              period_start=min(left.shift_date, right.shift_date),
                              period_end=max(left.shift_date, right.shift_date)))

    linked_notes: dict[str, list[NoteClassification]] = {}
    for note in notes:
        if note.linked_shift_id in unique_shifts:
            linked_notes.setdefault(note.linked_shift_id, []).append(note)
        elif note.linked_shift_id is None:
            # Unmatched notes retain their own text and row in the classification
            # export; without a shift date they cannot enter a period/site action.
            actions.append(Action("unmatched_note", "Confirm the shift ID before attributing this note.",
                                  f"Note row {note.source_row} does not link to one valid shift.",
                                  (SourceRecord("shift_notes.csv", note.source_row or 0, note.shift_id),)))

    relief_groups: dict[tuple[str, date], dict[str, tuple[SourceRecord, ...]]] = {}
    for shift_id, shift_notes in linked_notes.items():
        shift = unique_shifts[shift_id]
        if shift.shift_date is None or shift.shift_date >= cutoff.date() or shift.site_id not in ingestion.sites_by_id:
            continue
        if len({note.category for note in shift_notes}) > 1:
            if shift.shift_date >= week:
                actions.append(Action("conflicting_notes", "Confirm the cause recorded for this shift.",
                                      f"Shift {shift_id} has notes with conflicting categories; no cause was selected.",
                                      (unique_shift_sources[shift_id],) + tuple(SourceRecord("shift_notes.csv", note.source_row or 0,
                                       note.shift_id, shift.shift_date) for note in shift_notes),
                                      shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date))
            continue
        note_sources = tuple(SourceRecord("shift_notes.csv", note.source_row or 0, note.shift_id, shift.shift_date)
                             for note in shift_notes)
        evidence = (unique_shift_sources[shift_id],) + note_sources
        category = shift_notes[0].category
        if category == "relief_problem":
            period = shift.week_start
            relief_groups.setdefault((shift.site_id, period), {})[shift_id] = evidence
        if shift.shift_date < week:
            continue
        wording = "; ".join(f"row {note.source_row}: {note.note}" for note in shift_notes)
        if category == "equipment_failure":
            actions.append(Action("equipment_note", "Check the equipment issue and its status at the recorded site.",
                                  f"Shift {shift_id} notes say: {wording}", evidence,
                                  shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date))
        elif category == "client_requested" and all(note.explicit_client_request for note in shift_notes):
            approvals = "; ".join(f"row {note.source_row}: {note.approval_status}" for note in shift_notes)
            actions.append(Action("client_scope", "Confirm the requested scope and authorisation for this recorded work.",
                                  f"Shift {shift_id} notes say: {wording}. Approval status: {approvals}; "
                                  "approval does not establish billing entitlement.", evidence,
                                  shift.employee_id, shift.site_id, shift.shift_date, shift.shift_date))

    for (site_id, period), by_shift in sorted(relief_groups.items()):
        if len(by_shift) < 2:
            continue
        sources = tuple(source for evidence in by_shift.values() for source in evidence)
        actions.append(Action("relief_pattern", "Review the repeated relief handover reports at this site.",
                              f"{len(by_shift)} distinct shifts at actual site {site_id} in {period}–{period + timedelta(days=6)} "
                              "have relief-problem notes; this is a reporting pattern, not proof of misconduct.",
                              sources, site_id=site_id, period_start=period, period_end=period + timedelta(days=6)))
    return tuple(actions)


def action_evidence_rows(actions: tuple[Action, ...]) -> tuple[dict[str, str | int | float | None], ...]:
    """One row per supporting source, safe for display without payroll fields."""
    return tuple({"Kind": action.kind, "Employee ID": action.employee_id or "", "Actual site ID": action.site_id or "",
                  "Period start": action.period_start.isoformat() if action.period_start else "",
                  "Period end": action.period_end.isoformat() if action.period_end else "",
                  "Recommendation": action.recommendation, "Reason": action.reason,
                  "Source file": source.file, "Source row": source.row, "Source key": source.key,
                  "Source shift date": source.shift_date.isoformat() if source.shift_date else "",
                  "Recorded hours": action.recorded_hours, "Estimated elapsed hours": action.estimated_elapsed_hours,
                  "Estimated carry hours": action.estimated_carry_hours,
                  "Remaining hours before 55": action.remaining_hours_before_55,
                  "Risk score": action.risk_score}
                 for action in actions for source in action.sources)
