"""Streamlit presentation for the shared Jem ingestion and prediction pipeline."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from jem.io import demo_sources
from jem.pipeline import ingest
from jem.predictors.base import ProcessingError
from jem.workflow import ProcessedBundle, employee_note_rows, employee_shift_rows, filter_queue, input_fingerprint, load_policy, process_bundle, queue_counts, source_fingerprint


ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "config" / "prediction_policy.toml"
VIEWS = ("This week", "Overtime reasons", "Load data & checks")


def _init_session() -> None:
    defaults = {
        "uploaded_sources": {}, "upload_generation": 0, "upload_locked_source": None,
        "upload_error": None, "active_result": None, "active_token": None,
        "selected_as_of": None, "as_of_source": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _upload_controls() -> None:
    st.subheader("Replacement bundle")
    st.caption("Select the CSV files for one complete replacement export. Files stay in this browser session and are not durably stored.")
    if st.button("Start a new replacement upload"):
        st.session_state.upload_generation += 1
        st.session_state.uploaded_sources = {}
        st.session_state.upload_locked_source = None
        st.session_state.upload_error = None
        st.session_state.active_result = None
        st.session_state.active_token = None
        st.session_state.selected_as_of = None
        st.session_state.as_of_source = None
        st.rerun()
    uploaded = st.file_uploader("Select same-format CSV files", type="csv", accept_multiple_files=True,
                                key=f"bundle_upload_{st.session_state.upload_generation}")
    if uploaded:
        names = [item.name for item in uploaded]
        if len(names) != len(set(names)):
            st.session_state.upload_error = "Duplicate filenames selected. Start a new replacement upload and select one file per name."
            st.session_state.active_result = None
            st.session_state.active_token = None
        else:
            candidate = {item.name: item.getvalue() for item in uploaded}
            candidate_id = source_fingerprint(candidate)
            locked = st.session_state.upload_locked_source
            if locked is not None and candidate_id != locked:
                st.session_state.upload_error = "The processed upload changed. Start a new replacement upload so files from different selections cannot be combined."
                st.session_state.active_result = None
                st.session_state.active_token = None
            else:
                st.session_state.uploaded_sources = candidate
                st.session_state.upload_error = None
    if st.session_state.upload_error:
        st.error(st.session_state.upload_error)


def _preview_panel(preview, *, source_name: str) -> None:
    report = preview.reporting
    st.subheader("Coverage and checks")
    st.caption(f"Source: {source_name}. Row counts exclude unused payroll details and never show sensitive row contents.")
    if preview.bundle.row_counts:
        st.dataframe([{"File": name, "Rows": count} for name, count in preview.bundle.row_counts.items()],
                     hide_index=True, width="stretch")
    if report.first_shift_date and report.last_shift_date:
        st.write(f"Shift start dates: {report.first_shift_date} to {report.last_shift_date}.")
        st.write(f"Selected reporting week: {report.week_start} to {report.week_end}. {report.explanation}")
        st.caption(f"Historical support indicator: {report.historical_state}. The predictor checks actual clean reference rows before scoring.")
    errors = sum(issue.severity == "error" for issue in preview.issues)
    warnings = sum(issue.severity == "warning" for issue in preview.issues)
    st.write(f"Checks: {errors} blocking errors, {warnings} row or coverage warnings.")
    if preview.issues:
        st.dataframe([{"File": issue.file, "Row": issue.row, "Key": issue.key,
                       "Severity": issue.severity, "Issue": issue.issue,
                       "Suggested correction": issue.suggested_correction} for issue in preview.issues],
                     hide_index=True, width="stretch")
    for message in preview.unavailable_outputs:
        st.info(message)


def _load_view(preview, policy, token: str | None, source_id: str | None) -> None:
    st.caption("Each uploaded bundle replaces the previous one. Rejected or changed inputs clear the displayed predictions.")
    if st.session_state.source_mode == "Replacement upload":
        if not st.session_state.uploaded_sources:
            st.info("Select a complete replacement bundle to preview its coverage and checks.")
            return
        if st.session_state.upload_error:
            return
    if preview is None:
        st.warning("No bundle selected.")
        return
    _preview_panel(preview, source_name="Bundled synthetic demo" if st.session_state.source_mode == "Bundled demo" else "Session upload")
    if preview.reporting.mode == "before_wednesday":
        st.warning("This selection ends before Wednesday. A complete Wednesday forecast cannot be produced from it.")
    if st.button("Process bundle", disabled=not preview.accepted or preview.reporting.mode in ("before_wednesday", "unavailable")):
        try:
            processed = process_bundle(preview, policy)
        except (ProcessingError, ValueError) as exc:
            st.session_state.active_result = None
            st.session_state.active_token = None
            st.error(str(exc))
        else:
            st.session_state.active_result = processed
            st.session_state.active_token = token
            if st.session_state.source_mode == "Replacement upload":
                st.session_state.upload_locked_source = source_id
            st.success(f"Processed {len(processed.queue)} registered employees. Open This week to review predictions.")
    elif st.session_state.active_result is not None and st.session_state.active_token == token:
        st.success("This bundle is processed. Open This week to review predictions.")


def _queue_table(rows) -> list[dict[str, str]]:
    return [{"Employee": entry.name, "Site": entry.primary_site_id or "—",
             "Risk": f"{entry.forecast.risk_score:.1%}",
             "Status": ("Alert + review" if entry.forecast.will_breach and entry.needs_review else
                        "Alert" if entry.forecast.will_breach else
                        "Review" if entry.needs_review else "No alert")}
            for entry in rows]


def _employee_detail(processed: ProcessedBundle, entry) -> None:
    snapshot = entry.snapshot
    forecast = entry.forecast
    st.subheader(f"{entry.name} · {entry.employee_id}")
    st.caption(f"Queue site: {entry.primary_site_name} ({entry.primary_site_id or 'unassigned'}). Shift sites below are the places recorded for the work.")
    st.write(f"**Decision:** {'Breach alert' if forecast.will_breach else 'No breach alert'} · "
             f"**Risk score:** {forecast.risk_score:.1%} · **Method:** {forecast.method_version}")
    st.write(f"Completed recorded hours by cutoff: **{snapshot.known_hours:.2f} h**. "
             f"Estimated elapsed addition: **{snapshot.imputed_elapsed:.2f} h**. "
             f"Estimated overnight carry: **{snapshot.carry:.2f} h**.")
    if entry.review_reasons:
        st.warning("Data review: " + "; ".join(entry.review_reasons) + ".")
    else:
        st.caption("No current shift-quality flag was found. Recorded hours remain subject to the export's completeness limits.")
    if snapshot.overlapping_records:
        st.caption("The completed recorded sum includes overlapping intervals and is suspect; it is not a confirmed worked-hours total or confirmed breach.")
    if snapshot.no_records:
        st.caption("No dated shift is recorded through Wednesday. This does not prove zero final-week hours or zero risk.")
    st.write(f"**Historical support:** {forecast.support}. "
             f"Fallback: {forecast.fallback or 'role and shift-pattern peers with personal history'}.")
    st.caption("The score uses Wednesday hours and earlier completed employee-weeks. Supervisor notes may explain recorded hours; they are not inputs to this score.")
    shift_rows = employee_shift_rows(processed, entry.employee_id)
    st.markdown("**Shifts through Wednesday**")
    if shift_rows:
        st.dataframe([{"Date": row["Start date"], "Actual shift site": row["Actual shift site"],
                       "Recorded h": row["Recorded hours"], "Status": row["Status"]} for row in shift_rows],
                     hide_index=True, width="stretch")
        with st.expander("Shift IDs, times and overlap flags"):
            st.dataframe(shift_rows, hide_index=True, width="stretch")
    else:
        st.info("No dated shift record through Wednesday for this employee.")
    note_rows = employee_note_rows(processed, entry.employee_id)
    st.markdown("**Supervisor notes linked through Wednesday**")
    if note_rows:
        st.dataframe(note_rows, hide_index=True, width="stretch")
        st.caption("These notes describe recorded shifts. Their categories do not enter this risk score; approval is separate from cause.")
    else:
        st.caption("No uniquely linked supervisor note is available through Wednesday for this employee.")


def _this_week(processed: ProcessedBundle | None) -> None:
    st.title("This week")
    if processed is None:
        st.warning("No predictions are active for the selected inputs. Open Load data & checks to process this bundle.")
        return
    report = processed.ingestion.reporting
    first = processed.queue[0].forecast
    st.caption(f"{report.week_start}–{report.week_end} · As of {report.as_of} · {report.mode.replace('_', ' ')} · {first.method_version}")
    st.write(report.explanation)
    st.info(f"Breach alerts use the fixed {first.threshold:.0%} risk threshold selected for recall from earlier forecasts. "
            "A flagged employee is not necessarily more likely than not to breach.")
    all_entries = processed.queue
    sites = sorted({(entry.primary_site_id, entry.primary_site_name) for entry in all_entries}, key=lambda item: item[1])
    options = ["All primary sites"] + [f"{name} ({identifier or 'unassigned'})" for identifier, name in sites]
    selected_site = st.selectbox("Primary site filter", options)
    site_map = dict(zip(options[1:], (identifier for identifier, _ in sites)))
    ordered = filter_queue(processed, None if selected_site == "All primary sites" else site_map[selected_site])
    employee_count, alerts, review = queue_counts(ordered)
    left, middle, right = st.columns(3)
    left.metric("Employees", employee_count)
    middle.metric("Breach alerts", alerts)
    right.metric("Data review", review)
    st.caption("Alert = the model flags possible >55-hour final week. Review = records need checking. Both can apply. Site codes are registered primary sites; full names appear in the filter and details.")
    st.dataframe(_queue_table(ordered), hide_index=True, width="stretch")
    if ordered:
        lookup = {f"{entry.name} · {entry.employee_id}": entry for entry in ordered}
        selected = st.selectbox("Inspect an employee", list(lookup))
        _employee_detail(processed, lookup[selected])
    st.download_button("Download predictions.csv", data=processed.predictions_csv,
                       file_name="predictions.csv", mime="text/csv")
    with st.expander("Methodology and evidence"):
        st.write("Target: final Monday–Sunday recorded hours strictly greater than 55. The forecast masks clock-outs after Thursday 00:00 South African local time; record-entry timing cannot be proven from this export. Estimated elapsed hours are kept separate from completed recorded hours.")
        st.write(f"Method: {first.method_version}. Threshold: {first.threshold:.2f}. Policy: {processed.policy.threshold_rule}.")
        st.write("The six-week shared-code replay matched the supplied notebook: correlated hours caught 24 of 44 eligible breaches with 137 false alerts; naive caught 23 with 260. This is exploratory replay on the same supplied export, not independent validation or performance on uncertain outcomes.")
        st.write("Overlaps are flagged without repair. Missing or future clock-outs remain uncertain. Note categories are separate from the breach predictor. One human review sample found classification disagreements; see NOTES.md for the check and its limits.")


def _reasons(processed: ProcessedBundle | None, preview) -> None:
    st.title("Overtime reasons")
    if processed is None:
        st.warning("No processed results are active for the selected inputs. Open Load data & checks to process this bundle.")
        return
    if "shift_notes.csv" not in processed.ingestion.bundle.tables or any(
        message.startswith("Note classification unavailable") for message in processed.ingestion.unavailable_outputs):
        st.warning("No usable shift_notes.csv was supplied. Note classifications and cause association are unavailable.")
        return
    report = processed.attribution
    st.caption(f"Rules: {report.rules_version}. {len(processed.note_classifications)} source notes classified; original text is preserved in the download.")
    st.info("A human review sample found classification disagreements; the rules remain unchanged after that review. Hours below are associated with note categories, not proven causes or billable hours. Approval is separate from cause.")
    st.write(f"Completed clean historical employee-weeks included: **{report.eligible_employee_weeks}**. "
             f"Excluded historical employee-weeks: **{report.excluded_employee_weeks}**. "
             "The selected reporting week's partial notes are excluded from these hour totals.")
    if report.exclusion_reasons:
        with st.expander("Excluded coverage reasons"):
            st.dataframe([{"Reason": reason, "Employee-weeks": count} for reason, count in report.exclusion_reasons.items()],
                         hide_index=True, width="stretch")
    st.subheader("Historical overtime association")
    st.dataframe([{"Association": label, "Hours": report.pile_hours[pile],
                   "Share of all allocated overtime": report.pile_hours[pile] / report.total_overtime_hours if report.total_overtime_hours else 0.0}
                  for pile, label in (("client_requested", "Client requested"),
                                      ("operational_associated", "Operational associated"),
                                      ("unknown", "Unknown or unattributed"))], hide_index=True, width="stretch")
    st.caption(f"Denominator: {report.total_overtime_hours:.2f} recorded overtime hours in eligible historical weeks, including shifts with no note. Ordinary hours are assigned to the first 45 recorded hours in each employee-week.")
    st.subheader("Actual shift sites")
    st.dataframe([{"Site": site.site_name, "Site ID": site.site_id,
                   "Recorded hours": site.recorded_hours, "Overtime hours": site.total_overtime_hours,
                   "Client requested": site.client_requested_hours,
                   "Operational associated": site.operational_associated_hours,
                   "Unknown or unattributed": site.unknown_hours}
                  for site in report.site_summaries], hide_index=True, width="stretch")
    st.download_button("Download note_classifications.csv", data=processed.note_classifications_csv,
                       file_name="note_classifications.csv", mime="text/csv")
    with st.expander("Classification evidence for reviewers"):
        st.caption("Separate audit columns include original and matching text, typo corrections, linked shift, request and approval evidence, review flags and rules version.")
        st.download_button("Download note evidence CSV", data=processed.note_evidence_csv,
                           file_name="note_classification_evidence.csv", mime="text/csv")
    st.caption("This week's notes appear in employee details through Wednesday. They do not explain the correlated-hours risk score.")


def main() -> None:
    st.set_page_config(page_title="Jem overtime early warning", page_icon="⏱️")
    _init_session()
    policy = load_policy(POLICY_PATH)
    view = st.sidebar.radio("View", VIEWS, key="view")
    st.sidebar.radio("Data source", ("Bundled demo", "Replacement upload"), key="source_mode")
    st.sidebar.title("Jem overtime early warning")
    st.sidebar.caption("Uploads are kept only in this browser session.")
    if view == "Load data & checks":
        st.title("Load data & checks")
    if view == "Load data & checks" and st.session_state.source_mode == "Replacement upload":
        _upload_controls()
    sources = demo_sources(ROOT) if st.session_state.source_mode == "Bundled demo" else st.session_state.uploaded_sources
    preview = None
    token = None
    source_id = None
    if sources and not st.session_state.upload_error:
        source_id = source_fingerprint(sources)
        default_preview = ingest(sources)
        if st.session_state.as_of_source != source_id:
            st.session_state.as_of_source = source_id
            st.session_state.selected_as_of = default_preview.reporting.as_of
        if view == "Load data & checks" and default_preview.reporting.as_of is not None:
            st.session_state.selected_as_of = st.date_input("Reporting as-of date", value=st.session_state.selected_as_of,
                                                             key=f"as_of_{source_id[:12]}")
        as_of = st.session_state.selected_as_of
        preview = ingest(sources, as_of=as_of)
        if as_of is not None:
            token = input_fingerprint(sources, as_of, policy)
    if token != st.session_state.active_token:
        st.session_state.active_result = None
        st.session_state.active_token = None
    if st.session_state.source_mode == "Bundled demo" and preview is not None and preview.accepted and st.session_state.active_result is None:
        try:
            st.session_state.active_result = process_bundle(preview, policy)
            st.session_state.active_token = token
        except (ProcessingError, ValueError) as exc:
            st.error(f"Demo processing failed: {exc}")
    processed = st.session_state.active_result
    if view == "This week":
        _this_week(processed)
    elif view == "Overtime reasons":
        _reasons(processed, preview)
    else:
        _load_view(preview, policy, token, source_id)


if __name__ == "__main__":
    main()
