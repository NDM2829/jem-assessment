"""Local wall-clock shift parsing and overlap audit, independent of prediction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
import re
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Shift:
    shift_id: str
    employee_id: str
    site_id: str
    shift_date: date | None
    start_at: datetime | None
    end_at: datetime | None
    recorded_hours: float | None
    missing_clockout: bool
    invalid_time: bool
    overnight: bool
    excluded_reason: str | None = None

    @property
    def week_start(self) -> date | None:
        return self.shift_date - timedelta(days=self.shift_date.weekday()) if self.shift_date else None


@dataclass(frozen=True)
class Overlap:
    employee_id: str
    shift_id_left: str
    shift_id_right: str
    overlap_hours: float


def _clock(value: str) -> time | None:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value.strip()):
        return None
    return time.fromisoformat(value.strip())


def parse_shift(row: Mapping[str, str]) -> Shift:
    """Apply the notebook's <24-hour overnight convention without repairing rows."""
    date_text = row.get("shift_date", "")
    try:
        day = date.fromisoformat(date_text) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text) else None
    except ValueError:
        day = None
    start_clock = _clock(row.get("clock_in_time", ""))
    out_text = row.get("clock_out_time", "")
    end_clock = _clock(out_text)
    missing = not out_text.strip()
    start = datetime.combine(day, start_clock) if day and start_clock else None
    end = datetime.combine(day, end_clock) if day and end_clock else None
    overnight = bool(start_clock and end_clock and end_clock < start_clock)
    if end and overnight:
        end += timedelta(days=1)
    duration = (end - start).total_seconds() / 3600 if start and end else None
    invalid = day is None or start_clock is None or (not missing and end_clock is None) or (duration is not None and (duration <= 0 or duration >= 24))
    return Shift(row.get("shift_id", ""), row.get("employee_id", ""), row.get("site_id", ""), day,
                 start, end, None if invalid else duration, missing, invalid, overnight)


def mask_after_cutoff(shift: Shift, cutoff: datetime) -> Shift:
    """Hide a future end before computing any predictor-facing duration."""
    end = None if shift.end_at and shift.end_at > cutoff else shift.end_at
    duration = (end - shift.start_at).total_seconds() / 3600 if end and shift.start_at else None
    if duration is not None and not 0 < duration < 24:
        duration = None
    return replace(shift, end_at=end, recorded_hours=duration)


def find_overlaps(shifts: Iterable[Shift]) -> tuple[Overlap, ...]:
    """Report every positive intersection; touching endpoints do not overlap."""
    by_person: dict[str, list[Shift]] = {}
    for shift in shifts:
        if shift.recorded_hours is not None and shift.start_at and shift.end_at:
            by_person.setdefault(shift.employee_id, []).append(shift)
    pairs = []
    for employee_id, rows in by_person.items():
        active: list[Shift] = []
        for row in sorted(rows, key=lambda item: (item.start_at, item.shift_id)):
            active = [prior for prior in active if prior.end_at > row.start_at]
            for prior in active:
                overlap = (min(prior.end_at, row.end_at) - row.start_at).total_seconds() / 3600
                if overlap > 0:
                    pairs.append(Overlap(employee_id, prior.shift_id, row.shift_id, overlap))
            active.append(row)
    return tuple(pairs)
