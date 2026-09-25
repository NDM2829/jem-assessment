"""Past-only Wednesday snapshots and separate clean historical outcomes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from statistics import mean

from jem.hours import Shift, find_overlaps, mask_after_cutoff, parse_shift
from jem.pipeline import IngestionResult


DURATION_PRIOR_SHIFTS = 10
MINIMUM_PEER_SHIFTS = 10
BREACH_HOURS = 55.0


@dataclass(frozen=True)
class Snapshot:
    employee_id: str
    week_start: date
    role: str
    shift_pattern: str
    known_hours: float
    imputed_elapsed: float
    carry: float
    days: int
    unknown_records: int
    overlapping_records: int
    records: int
    duration_estimate: float | None
    overlap_shift_ids: tuple[str, ...]
    no_records: bool
    missing_clockouts: int = 0
    future_end_masked: int = 0
    invalid_time_records: int = 0
    excluded_shift_records: int = 0
    undated_shift_records: int = 0

    @property
    def A(self) -> float:
        return self.known_hours + self.imputed_elapsed


@dataclass(frozen=True)
class Outcome:
    employee_id: str
    week_start: date
    recorded_hours: float
    total_days: int
    shift_count: int
    missing_clockouts: int
    invalid_times: int
    overlapping_shifts: int
    calendar_coverage_ok: bool
    exclusion_reasons: tuple[str, ...]
    target_will_breach: bool | None

    @property
    def label_eligible(self) -> bool:
        return not self.exclusion_reasons


@dataclass(frozen=True)
class HistoricalRow:
    snapshot: Snapshot
    outcome: Outcome
    A: float
    R: float
    total_hours: float
    total_days: int


@dataclass(frozen=True)
class Reconciliation:
    employee_id: str
    week_start: date
    recorded_hours: float | None
    exported_total_hours: float | None
    difference: float | None
    status: str


def source_shifts(result: IngestionResult) -> tuple[Shift, ...]:
    if not result.accepted:
        raise ValueError("Correct ingestion errors before building hours features.")
    table = result.bundle.tables["shifts.csv"]
    rows = []
    for row in table.rows:
        shift = parse_shift(row)
        if row.get("shift_id") not in result.shifts_by_id:
            # Preserve the source row as uncertainty, without counting or
            # estimating its ambiguous duration as another worked shift.
            shift = replace(shift, end_at=None, recorded_hours=None, invalid_time=True,
                            excluded_reason="ambiguous_shift_id")
        rows.append(shift)
    return tuple(rows)


def reporting_weeks(shifts: tuple[Shift, ...], selected_week: date) -> tuple[date, ...]:
    dates = [s.week_start for s in shifts if s.week_start and s.week_start <= selected_week]
    if not dates:
        return ()
    first = min(dates)
    return tuple(first + timedelta(days=7 * i) for i in range((selected_week - first).days // 7 + 1))


def _duration_estimates(shifts: tuple[Shift, ...], employees: dict[str, dict[str, str]], week: date) -> dict[str, float | None]:
    past = [s for s in shifts if s.week_start and s.week_start < week]
    overlap_ids = {identifier for pair in find_overlaps(past) for identifier in (pair.shift_id_left, pair.shift_id_right)}
    valid = [s for s in past if s.recorded_hours is not None and s.shift_id not in overlap_ids and s.employee_id in employees]
    estimates: dict[str, float | None] = {}
    for employee_id, employee in employees.items():
        own = [s.recorded_hours for s in valid if s.employee_id == employee_id]
        peers = [s.recorded_hours for s in valid if s.employee_id != employee_id
                 and employees[s.employee_id].get("role") == employee.get("role")
                 and employees[s.employee_id].get("shift_pattern") == employee.get("shift_pattern")]
        if len(peers) < MINIMUM_PEER_SHIFTS:
            peers = [s.recorded_hours for s in valid if s.employee_id != employee_id]
        peer_mean = mean(peers) if peers else mean(own) if own else None
        estimates[employee_id] = (sum(own) + DURATION_PRIOR_SHIFTS * peer_mean) / (len(own) + DURATION_PRIOR_SHIFTS) if peer_mean is not None else None
    return estimates


def build_snapshot(shifts: tuple[Shift, ...], employees: dict[str, dict[str, str]], week: date) -> tuple[Snapshot, ...]:
    """One Thursday-00:00 snapshot per registered employee, including no records."""
    if week.weekday() != 0:
        raise ValueError("Reporting week must start on Monday.")
    cutoff = datetime.combine(week + timedelta(days=3), time.min)
    estimates = _duration_estimates(shifts, employees, week)
    visible = [mask_after_cutoff(s, cutoff) for s in shifts if s.shift_date and week - timedelta(days=1) <= s.shift_date < cutoff.date()]
    original_ends = {s.shift_id: s.end_at for s in shifts}
    overlap_ids = {identifier for pair in find_overlaps(visible) for identifier in (pair.shift_id_left, pair.shift_id_right)}
    current = [s for s in visible if s.shift_date >= week]
    rows = []
    for employee_id, employee in employees.items():
        group = [s for s in current if s.employee_id == employee_id]
        known = sum(s.recorded_hours or 0.0 for s in group)
        estimated = 0.0
        carry = 0.0
        estimate = estimates[employee_id]
        for shift in group:
            if shift.recorded_hours is not None or estimate is None or shift.excluded_reason:
                continue
            elapsed = 24.0 if shift.start_at is None else max(0.0, (cutoff - shift.start_at).total_seconds() / 3600)
            estimated += min(estimate, elapsed)
            carry += max(estimate - elapsed, 0.0)
        rows.append(Snapshot(employee_id, week, employee.get("role", ""), employee.get("shift_pattern", ""),
                             known, estimated, carry, len({s.shift_date for s in group}),
                             sum(s.recorded_hours is None for s in group),
                             sum(s.shift_id in overlap_ids for s in group), len(group), estimate,
                             tuple(s.shift_id for s in group if s.shift_id in overlap_ids), not group,
                             sum(s.missing_clockout for s in group),
                             sum(bool(original_ends[s.shift_id] and original_ends[s.shift_id] > cutoff) for s in group),
                             sum(s.invalid_time for s in group),
                             sum(bool(s.excluded_reason) for s in group),
                             sum(s.employee_id == employee_id and s.shift_date is None for s in shifts)))
    return tuple(rows)


def build_outcomes(shifts: tuple[Shift, ...], employees: dict[str, dict[str, str]], selected_week: date) -> tuple[Outcome, ...]:
    """Observed recorded sums and conservative eligibility, never predictor inputs."""
    rows = []
    undated_employees = {s.employee_id for s in shifts if s.shift_date is None}
    for week in reporting_weeks(shifts, selected_week):
        week_end = week + timedelta(days=6)
        prior = [s for s in shifts if s.shift_date and week - timedelta(days=1) <= s.shift_date <= week_end]
        overlap_ids = {identifier for pair in find_overlaps(prior) for identifier in (pair.shift_id_left, pair.shift_id_right)}
        current = [s for s in prior if s.shift_date >= week]
        calendar_ok = len({s.shift_date for s in current}) == 7 and week < selected_week
        for employee_id in employees:
            group = [s for s in current if s.employee_id == employee_id]
            recorded = sum(s.recorded_hours or 0.0 for s in group)
            missing = sum(s.missing_clockout for s in group)
            invalid = sum(s.invalid_time for s in group)
            overlaps = sum(s.shift_id in overlap_ids for s in group)
            reasons = []
            if week == selected_week:
                reasons.append("reserved_current_week")
            if not calendar_ok:
                reasons.append("incomplete_calendar_coverage")
            if not group:
                reasons.append("no_shift_records")
            if missing:
                reasons.append("missing_clockout")
            if invalid:
                reasons.append("invalid_time")
            if employee_id in undated_employees:
                reasons.append("undated_shift_record")
            if overlaps:
                reasons.append("overlap")
            rows.append(Outcome(employee_id, week, recorded, len({s.shift_date for s in group}), len(group),
                                missing, invalid, overlaps, calendar_ok, tuple(reasons),
                                recorded > BREACH_HOURS if not reasons else None))
    return tuple(rows)


def build_history(shifts: tuple[Shift, ...], employees: dict[str, dict[str, str]], selected_week: date) -> tuple[HistoricalRow, ...]:
    outcomes = {(o.employee_id, o.week_start): o for o in build_outcomes(shifts, employees, selected_week)}
    first_week = min(reporting_weeks(shifts, selected_week), default=None)
    rows = []
    for week in reporting_weeks(shifts, selected_week):
        if week >= selected_week:
            break
        cutoff = datetime.combine(week + timedelta(days=3), time.min)
        for snap in build_snapshot(shifts, employees, week):
            outcome = outcomes[(snap.employee_id, week)]
            a = snap.A
            if week == first_week and outcome.label_eligible:
                # Reference-only W1 uses eventual completed elapsed hours at cutoff.
                prefix = [s for s in shifts if s.employee_id == snap.employee_id and s.shift_date
                          and week <= s.shift_date < cutoff.date() and s.start_at and s.end_at]
                a = sum((min(s.end_at, cutoff) - s.start_at).total_seconds() / 3600 for s in prefix)
            rows.append(HistoricalRow(snap, outcome, a, outcome.recorded_hours - a,
                                      outcome.recorded_hours, outcome.total_days))
    return tuple(rows)


def reconcile_weekly_summary(result: IngestionResult, outcomes: tuple[Outcome, ...]) -> tuple[Reconciliation, ...]:
    """Audit exported arithmetic separately; never use summary totals as truth or X."""
    table = result.bundle.tables.get("weekly_summary.csv")
    if table is None or not {"employee_id", "week_starting", "total_hours"}.issubset(table.columns):
        return ()
    summary: dict[tuple[str, date], list[float | None]] = {}
    for row in table.rows:
        try:
            week = date.fromisoformat(row["week_starting"])
            total = float(row["total_hours"])
        except ValueError:
            continue
        if total < 0 or not (total < float("inf")):
            continue
        summary.setdefault((row["employee_id"], week), []).append(total)
    rows = []
    for outcome in outcomes:
        values = summary.get((outcome.employee_id, outcome.week_start), [])
        if not values:
            rows.append(Reconciliation(outcome.employee_id, outcome.week_start, outcome.recorded_hours, None, None, "missing_summary"))
        elif len(values) > 1:
            rows.append(Reconciliation(outcome.employee_id, outcome.week_start, outcome.recorded_hours, None, None, "ambiguous_summary"))
        else:
            difference = outcome.recorded_hours - values[0]
            rows.append(Reconciliation(outcome.employee_id, outcome.week_start, outcome.recorded_hours,
                                       values[0], difference, "matches" if abs(difference) <= 1e-8 else "differs"))
    return tuple(rows)
