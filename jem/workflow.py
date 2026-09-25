"""Session-safe processing and presentation facts shared by the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
from pathlib import Path
from typing import Mapping

import tomli

from jem.exports import predictions_csv_bytes
from jem.features import Snapshot, build_history, build_snapshot, source_shifts
from jem.hours import Shift, mask_after_cutoff
from jem.attribution import AttributionReport, allocate_overtime
from jem.notes import RULES_VERSION, NoteClassification, classify_bundle, note_classifications_csv_bytes, note_evidence_csv_bytes
from jem.pipeline import IngestionResult
from jem.predictors.base import Forecast, PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict


@dataclass(frozen=True)
class Policy:
    config: PredictorConfig
    digest: str
    threshold_rule: str


@dataclass(frozen=True)
class QueueEntry:
    employee_id: str
    name: str
    primary_site_id: str
    primary_site_name: str
    forecast: Forecast
    snapshot: Snapshot
    review_reasons: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)


@dataclass(frozen=True)
class ProcessedBundle:
    ingestion: IngestionResult
    policy: Policy
    shifts: tuple[Shift, ...]
    queue: tuple[QueueEntry, ...]
    predictions_csv: bytes
    note_classifications: tuple[NoteClassification, ...]
    note_classifications_csv: bytes
    note_evidence_csv: bytes
    attribution: AttributionReport


def load_policy(path: str | Path) -> Policy:
    data = Path(path).read_bytes()
    document = tomli.loads(data.decode("utf-8"))
    if document["initial_method"] != "correlated_hours":
        raise ProcessingError("The selected prediction method is not implemented in this stage.")
    deployment = document["deployment"]
    config = PredictorConfig(document["policy_version"], deployment["method_version"],
                             deployment["threshold"], deployment["personal_prior_weeks"],
                             deployment["peer_minimum_weeks"], deployment["variance_floor"],
                             deployment["correlation_cap"])
    return Policy(config, hashlib.sha256(data).hexdigest(), deployment["threshold_rule"])


def source_fingerprint(sources: Mapping[str, bytes | Path]) -> str:
    digest = hashlib.sha256()
    for name, source in sorted(sources.items()):
        raw = source if isinstance(source, bytes) else Path(source).read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def input_fingerprint(sources: Mapping[str, bytes | Path], as_of: date, policy: Policy) -> str:
    digest = hashlib.sha256()
    digest.update(source_fingerprint(sources).encode("ascii"))
    digest.update(as_of.isoformat().encode("ascii"))
    digest.update(policy.digest.encode("ascii"))
    digest.update(RULES_VERSION.encode("ascii"))
    return digest.hexdigest()


def _review_reasons(snapshot: Snapshot) -> tuple[str, ...]:
    reasons = []
    if snapshot.overlapping_records:
        reasons.append("Overlapping shift intervals; recorded sum is suspect")
    if snapshot.missing_clockouts:
        reasons.append("Missing clock-out")
    if snapshot.future_end_masked:
        reasons.append("End after forecast cutoff was masked")
    if snapshot.invalid_time_records:
        reasons.append("Invalid or ambiguous shift time")
    if snapshot.excluded_shift_records:
        reasons.append("Ambiguous shift identifier")
    if snapshot.undated_shift_records:
        reasons.append("Undated shift record")
    if snapshot.no_records:
        reasons.append("No dated shift through Wednesday; final hours unknown")
    return tuple(reasons)


def process_bundle(ingestion: IngestionResult, policy: Policy) -> ProcessedBundle:
    if not ingestion.accepted or ingestion.reporting.week_start is None:
        raise ProcessingError("Correct the bundle errors before processing.")
    if ingestion.reporting.mode == "before_wednesday":
        raise ProcessingError("This export does not reach Wednesday; upload through Wednesday or select a covered replay week.")
    shifts = source_shifts(ingestion)
    week = ingestion.reporting.week_start
    history = build_history(shifts, ingestion.employees_by_id, week)
    snapshots = build_snapshot(shifts, ingestion.employees_by_id, week)
    forecasts = predict(snapshots, history, policy.config)
    by_forecast = {row.employee_id: row for row in forecasts}
    queue = []
    for snapshot in snapshots:
        employee = ingestion.employees_by_id[snapshot.employee_id]
        site_id = employee.get("primary_site_id", "")
        site = ingestion.sites_by_id.get(site_id, {})
        queue.append(QueueEntry(snapshot.employee_id, employee.get("full_name", snapshot.employee_id),
                                site_id, site.get("site_name", "Unassigned site"), by_forecast[snapshot.employee_id],
                                snapshot, _review_reasons(snapshot)))
    csv_data = predictions_csv_bytes(forecasts, set(ingestion.employees_by_id))
    classified = classify_bundle(ingestion)
    attribution = allocate_overtime(shifts, ingestion.employees_by_id, ingestion.sites_by_id, week, classified)
    return ProcessedBundle(ingestion, policy, shifts, tuple(queue), csv_data,
                           classified, note_classifications_csv_bytes(classified),
                           note_evidence_csv_bytes(classified), attribution)


def filter_queue(processed: ProcessedBundle, primary_site_id: str | None = None) -> tuple[QueueEntry, ...]:
    """Keep review cases in the queue regardless of their predicted risk."""
    rows = (entry for entry in processed.queue if primary_site_id is None or entry.primary_site_id == primary_site_id)
    return tuple(sorted(rows, key=lambda entry: (-int(entry.forecast.will_breach), -int(entry.needs_review),
                                                  -entry.forecast.risk_score, entry.employee_id)))


def queue_counts(entries: tuple[QueueEntry, ...]) -> tuple[int, int, int]:
    return len(entries), sum(entry.forecast.will_breach for entry in entries), sum(entry.needs_review for entry in entries)


def employee_shift_rows(processed: ProcessedBundle, employee_id: str) -> tuple[dict[str, str | float | None], ...]:
    """Shift evidence visible at the forecast cutoff, using actual shift sites."""
    week = processed.ingestion.reporting.week_start
    cutoff = datetime.combine(week + timedelta(days=3), time.min)
    rows = []
    for source in processed.shifts:
        if source.employee_id != employee_id or not source.shift_date or not week <= source.shift_date < cutoff.date():
            continue
        shift = mask_after_cutoff(source, cutoff)
        site = processed.ingestion.sites_by_id.get(shift.site_id, {})
        if source.excluded_reason:
            status = "Ambiguous ID; hours excluded"
        elif source.end_at and source.end_at > cutoff:
            status = "End after cutoff masked"
        elif source.missing_clockout:
            status = "Missing clock-out"
        elif source.invalid_time:
            status = "Invalid time"
        else:
            status = "Completed by cutoff"
        rows.append({"Shift ID": shift.shift_id, "Start date": shift.shift_date.isoformat(),
                     "Actual shift site": site.get("site_name", shift.site_id or "Unknown site"),
                     "Clock-in": source.start_at.strftime("%H:%M") if source.start_at else "Invalid",
                     "Clock-out at cutoff": shift.end_at.strftime("%Y-%m-%d %H:%M") if shift.end_at else "Unavailable",
                     "Recorded hours": shift.recorded_hours, "Status": status,
                     "Overlap flagged": shift.shift_id in next((entry.snapshot.overlap_shift_ids for entry in processed.queue if entry.employee_id == employee_id), ())})
    return tuple(sorted(rows, key=lambda row: (row["Start date"], row["Shift ID"])))


def employee_note_rows(processed: ProcessedBundle, employee_id: str) -> tuple[dict[str, str | int | bool], ...]:
    """Source notes for this employee's uniquely linked shifts through Wednesday."""
    week = processed.ingestion.reporting.week_start
    if week is None:
        return ()
    through = week + timedelta(days=3)
    shift_lookup = {shift.shift_id: shift for shift in processed.shifts if not shift.excluded_reason}
    rows = []
    for note in processed.note_classifications:
        shift = shift_lookup.get(note.linked_shift_id) if note.linked_shift_id else None
        if shift and shift.employee_id == employee_id and shift.shift_date and week <= shift.shift_date < through:
            rows.append({"Shift ID": note.shift_id, "Source row": note.source_row or 0,
                         "Note": note.note, "Category": note.category,
                         "Approval in note": note.approval_status, "Review": note.needs_review})
    return tuple(rows)
