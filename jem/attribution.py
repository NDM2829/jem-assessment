"""Historical recorded-overtime association with note causes and actual sites."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from math import isclose

from jem.features import build_outcomes
from jem.hours import Shift
from jem.notes import NoteClassification, RULES_VERSION


ORDINARY_HOURS = 45.0
PILES = ("client_requested", "operational_associated", "unknown")


@dataclass(frozen=True)
class AllocationRow:
    employee_id: str
    week_start: date
    shift_id: str
    site_id: str
    recorded_hours: float
    chronological_overtime_hours: float
    proportional_overtime_hours: float
    category: str
    cause_pile: str
    note_count: int


@dataclass(frozen=True)
class SiteSummary:
    site_id: str
    site_name: str
    recorded_hours: float
    total_overtime_hours: float
    client_requested_hours: float
    operational_associated_hours: float
    unknown_hours: float


@dataclass(frozen=True)
class AttributionReport:
    allocations: tuple[AllocationRow, ...]
    site_summaries: tuple[SiteSummary, ...]
    eligible_employee_weeks: int
    excluded_employee_weeks: int
    exclusion_reasons: dict[str, int]
    total_overtime_hours: float
    pile_hours: dict[str, float]
    rules_version: str


def _shift_cause(notes: tuple[NoteClassification, ...]) -> tuple[str, str]:
    if not notes:
        return "no_note", "unknown"
    categories = {note.category for note in notes}
    if len(categories) != 1:
        return "unclear_or_mixed", "unknown"
    category = next(iter(categories))
    return category, notes[0].cause_pile


def allocate_overtime(shifts: tuple[Shift, ...], employees: dict[str, dict[str, str]],
                      sites: dict[str, dict[str, str]], selected_week: date,
                      notes: tuple[NoteClassification, ...]) -> AttributionReport:
    """Allocate clean completed weeks after 45 recorded hours; never infer cause."""
    outcomes = build_outcomes(shifts, employees, selected_week)
    historical = [outcome for outcome in outcomes if outcome.week_start < selected_week]
    eligible = {(outcome.employee_id, outcome.week_start): outcome for outcome in historical if outcome.label_eligible}
    excluded = [outcome for outcome in historical if not outcome.label_eligible]
    reasons = Counter(reason for outcome in excluded for reason in outcome.exclusion_reasons)
    notes_by_shift: dict[str, list[NoteClassification]] = defaultdict(list)
    for note in notes:
        if note.linked_shift_id is not None:
            notes_by_shift[note.linked_shift_id].append(note)
    shifts_by_week: dict[tuple[str, date], list[Shift]] = defaultdict(list)
    for shift in shifts:
        if shift.week_start is not None and (shift.employee_id, shift.week_start) in eligible:
            shifts_by_week[(shift.employee_id, shift.week_start)].append(shift)
    allocations = []
    for key, outcome in sorted(eligible.items()):
        group = sorted(shifts_by_week[key], key=lambda row: (row.start_at, row.shift_id))
        recorded = sum(row.recorded_hours or 0.0 for row in group)
        if not isclose(recorded, outcome.recorded_hours, abs_tol=1e-8):
            raise ValueError("Clean historical shift hours do not reconcile to the outcome.")
        overtime = max(recorded - ORDINARY_HOURS, 0.0)
        cumulative = 0.0
        week_allocations = []
        for shift in group:
            if shift.recorded_hours is None or shift.start_at is None:
                raise ValueError("A clean historical week contains an unavailable shift duration.")
            before = max(cumulative - ORDINARY_HOURS, 0.0)
            cumulative += shift.recorded_hours
            chronological = max(cumulative - ORDINARY_HOURS, 0.0) - before
            proportional = overtime * shift.recorded_hours / recorded if recorded else 0.0
            linked = tuple(notes_by_shift.get(shift.shift_id, ()))
            category, pile = _shift_cause(linked)
            week_allocations.append(AllocationRow(shift.employee_id, outcome.week_start, shift.shift_id,
                                                  shift.site_id, shift.recorded_hours, chronological,
                                                  proportional, category, pile, len(linked)))
        if not isclose(sum(row.chronological_overtime_hours for row in week_allocations), overtime, abs_tol=1e-8):
            raise ValueError("Chronological overtime allocation does not reconcile.")
        if not isclose(sum(row.proportional_overtime_hours for row in week_allocations), overtime, abs_tol=1e-8):
            raise ValueError("Proportional sensitivity allocation does not reconcile.")
        allocations.extend(week_allocations)
    piles = {pile: sum(row.chronological_overtime_hours for row in allocations if row.cause_pile == pile)
             for pile in PILES}
    total = sum(piles.values())
    site_ids = sorted({row.site_id for row in allocations})
    summaries = []
    for site_id in site_ids:
        group = [row for row in allocations if row.site_id == site_id]
        by_pile = {pile: sum(row.chronological_overtime_hours for row in group if row.cause_pile == pile)
                   for pile in PILES}
        site_total = sum(row.chronological_overtime_hours for row in group)
        if not isclose(sum(by_pile.values()), site_total, abs_tol=1e-8):
            raise ValueError("Site overtime attribution does not reconcile.")
        summaries.append(SiteSummary(site_id, sites.get(site_id, {}).get("site_name", "Unknown site"),
                                     sum(row.recorded_hours for row in group), site_total,
                                     by_pile["client_requested"], by_pile["operational_associated"],
                                     by_pile["unknown"]))
    if not isclose(sum(row.total_overtime_hours for row in summaries), total, abs_tol=1e-8):
        raise ValueError("Overall overtime attribution does not reconcile.")
    return AttributionReport(tuple(allocations), tuple(summaries), len(eligible), len(excluded),
                             dict(sorted(reasons.items())), total, piles,
                             notes[0].rules_version if notes else RULES_VERSION)
