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
from jem.actions import Action, OPERATIONS_KINDS, REVIEW_KINDS, build_actions
from jem.notes import RULES_VERSION, NoteClassification, classify_bundle, note_classifications_csv_bytes, note_evidence_csv_bytes
from jem.pipeline import IngestionResult
from jem.predictors.base import Forecast, PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict as correlated_predict
from jem.predictors.smoothed_risk_table import predict as table_predict
from jem.predictors.matched_historical_remaining_hours import predict as matched_predict


SELECTED_PREDICTORS = {
    "correlated_hours": correlated_predict,
    "smoothed_risk_table": table_predict,
    "matched_historical_remaining_hours": matched_predict,
}


@dataclass(frozen=True)
class Policy:
    config: PredictorConfig
    digest: str
    threshold_rule: str
    selected_method: str = "correlated_hours"


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
    actions: tuple[Action, ...]


def load_policy(path: str | Path) -> Policy:
    data = Path(path).read_bytes()
    document = tomli.loads(data.decode("utf-8"))
    if document["initial_method"] != "correlated_hours":
        raise ProcessingError("The predeclared initial method must remain correlated hours.")
    deployment = document["deployment"]
    selected = deployment.get("selected_method", document["initial_method"])
    if selected not in SELECTED_PREDICTORS:
        raise ProcessingError("The selected statistical prediction method is unavailable.")
    prefixes = {"correlated_hours": "correlated-hours-", "smoothed_risk_table": "smoothed-risk-table-",
                "matched_historical_remaining_hours": "matched-remainder-"}
    if not deployment["method_version"].startswith(prefixes[selected]):
        raise ProcessingError("The configured method version does not match the selected predictor.")
    config = PredictorConfig(document["policy_version"], deployment["method_version"],
                             deployment["threshold"], deployment["personal_prior_weeks"],
                             deployment["peer_minimum_weeks"], deployment["variance_floor"],
                             deployment["correlation_cap"])
    return Policy(config, hashlib.sha256(data).hexdigest(), deployment["threshold_rule"], selected)


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
    forecasts = SELECTED_PREDICTORS[policy.selected_method](snapshots, history, policy.config)
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
    actions = build_actions(ingestion, shifts, snapshots, forecasts, classified)
    return ProcessedBundle(ingestion, policy, shifts, tuple(queue), csv_data,
                           classified, note_classifications_csv_bytes(classified),
                           note_evidence_csv_bytes(classified), attribution, actions)


def filter_queue(processed: ProcessedBundle, primary_site_id: str | None = None,
                 status: str = "All employees", search: str = "") -> tuple[QueueEntry, ...]:
    """Keep review cases in the queue regardless of their predicted risk."""
    rows = (entry for entry in processed.queue if primary_site_id is None or entry.primary_site_id == primary_site_id)
    if status == "Breach alerts":
        rows = (entry for entry in rows if entry.forecast.will_breach)
    elif status == "Records to check":
        rows = (entry for entry in rows if entry.needs_review)
    query = search.strip().casefold()
    if query:
        rows = (entry for entry in rows if query in entry.name.casefold() or query in entry.employee_id.casefold())
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
    return current_note_rows(processed, employee_id)


def current_note_rows(processed: ProcessedBundle, employee_id: str | None = None) -> tuple[dict, ...]:
    """Current linked notes only; undated/unmatched notes remain in audit exports."""
    week = processed.ingestion.reporting.week_start
    if week is None:
        return ()
    through = week + timedelta(days=3)
    shift_lookup = {shift.shift_id: shift for shift in processed.shifts if not shift.excluded_reason}
    rows = []
    for note in processed.note_classifications:
        shift = shift_lookup.get(note.linked_shift_id) if note.linked_shift_id else None
        if shift and (employee_id is None or shift.employee_id == employee_id) and shift.shift_date and week <= shift.shift_date < through:
            rows.append({"Shift ID": note.shift_id, "Source row": note.source_row or 0,
                         "Employee ID": shift.employee_id,
                         "Site": processed.ingestion.sites_by_id.get(shift.site_id, {}).get("site_name", shift.site_id),
                         "Note": note.note, "Category": note.category,
                         "Approval in note": note.approval_status, "Review": note.needs_review})
    return tuple(rows)


def employee_actions(processed: ProcessedBundle, employee_id: str) -> tuple[Action, ...]:
    """Show record corrections before allowances; preserve every supporting action."""
    review_order = {kind: index for index, kind in enumerate((
        "overlap", "missing_clockout", "invalid_shift", "cutoff_masked",
        "no_current_records", "conflicting_notes"))}
    return tuple(sorted((action for action in processed.actions
                         if action.employee_id == employee_id and action.kind != "unmatched_note"),
                        key=lambda action: (0 if action.kind in REVIEW_KINDS else
                                            1 if action.kind == "breach_alert" else 2,
                                            review_order.get(action.kind, len(review_order)),
                                            action.kind, str(action.period_start))))


def employee_table_rows(processed: ProcessedBundle, entries: tuple[QueueEntry, ...],
                        view: str) -> list[dict]:
    """One row per employee, with all required checks retained in the review view."""
    rows = []
    for entry in entries:
        row = {"Employee": entry.name, "Site": entry.primary_site_name}
        actions = employee_actions(processed, entry.employee_id)
        if view == "Records to check":
            checks = [action.recommendation for action in actions if action.kind in REVIEW_KINDS]
            row.update({"What to check": "\n".join(checks or entry.review_reasons),
                        "Breach alert": entry.forecast.will_breach})
        else:
            if view == "All employees":
                row["Breach alert"] = entry.forecast.will_breach
            row.update({"Risk": entry.forecast.risk_score * 100,
                        "Recorded h": None if entry.snapshot.no_records else entry.snapshot.known_hours,
                        "Records": ("No current records" if entry.snapshot.no_records else
                                    "Suspect: overlap" if entry.snapshot.overlapping_records else
                                    "Needs checking" if entry.needs_review else "No flag")})
            if view == "Breach alerts":
                row["Do today"] = actions[0].recommendation if actions else ""
        rows.append(row)
    return rows


def operational_actions(processed: ProcessedBundle, *, historical: bool = False) -> tuple[Action, ...]:
    week = processed.ingestion.reporting.week_start
    return tuple(action for action in processed.actions if action.kind in OPERATIONS_KINDS
                 and action.period_start is not None
                 and (action.period_start < week if historical else
                      week <= action.period_start <= processed.ingestion.reporting.week_end))


def attribution_summary(processed: ProcessedBundle) -> dict:
    """Shared historical display facts; no new allocation or cleaning policy."""
    report = processed.attribution
    rows = [{"Reason": label, "Hours": report.pile_hours[pile],
             "Share": report.pile_hours[pile] / report.total_overtime_hours if report.total_overtime_hours else 0.0}
            for pile, label in (("client_requested", "Client requested"),
                                ("operational_associated", "Operational issues"),
                                ("unknown", "Unknown or unattributed"))]
    weeks = [row.week_start for row in report.allocations]
    return {"rows": rows, "start": min(weeks) if weeks else None,
            "end": max(weeks) + timedelta(days=6) if weeks else None,
            "sites": tuple(sorted(report.site_summaries,
                                  key=lambda site: (-site.operational_associated_hours, site.site_name)))}
