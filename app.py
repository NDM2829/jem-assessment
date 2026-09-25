"""Manager-facing Streamlit views over the shared Jem workflow."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
import json
from pathlib import Path

import streamlit as st

from jem.actions import REVIEW_KINDS, action_evidence_rows
from jem.io import CORE_FILES, FILES, demo_sources
from jem.pipeline import ingest
from jem.predictors.base import ProcessingError
from jem.workflow import (
    ProcessedBundle, attribution_summary, current_note_rows, employee_actions,
    employee_note_rows, employee_shift_rows, employee_table_rows, filter_queue, input_fingerprint,
    load_policy, operational_actions, process_bundle, queue_counts, source_fingerprint,
)

ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "config" / "prediction_policy.toml"
VIEWS = ("Act today", "Why overtime", "Load new data")


def _init_session() -> None:
    defaults = {
        "uploaded_sources": {}, "upload_generation": 0, "upload_locked_source": None,
        "upload_error": None, "active_result": None, "active_token": None,
        "selected_as_of": None, "as_of_source": None, "source_mode": "Bundled demo",
        "view": "Act today", "selected_employee": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "next_view" in st.session_state:
        st.session_state.view = st.session_state.pop("next_view")


def _go(view: str) -> None:
    st.session_state.view = view
    st.session_state.selected_employee = None


def _select_employee(employee_id: str | None) -> None:
    st.session_state.selected_employee = employee_id
    if employee_id is None:
        st.session_state.employee_table = {"selection": {"rows": []}}


def _clear_result() -> None:
    st.session_state.active_result = None
    st.session_state.active_token = None
    st.session_state.selected_employee = None
    st.session_state.site_filter = "All sites"
    st.session_state.queue_status = "Breach alerts"
    st.session_state.employee_search = ""
    st.session_state.employee_table = {"selection": {"rows": []}}


def _new_upload() -> None:
    st.session_state.upload_generation += 1
    st.session_state.uploaded_sources = {}
    st.session_state.upload_locked_source = None
    st.session_state.upload_error = None
    st.session_state.selected_as_of = None
    st.session_state.as_of_source = None
    _clear_result()


def _read_upload(key: str) -> None:
    uploaded = st.session_state[key] or []
    _clear_result()
    names = [item.name for item in uploaded]
    if len(names) != len(set(names)):
        st.session_state.upload_error = "Duplicate filenames selected. Choose another export with one file per name."
        st.session_state.uploaded_sources = {}
        return
    candidate = {item.name: item.getvalue() for item in uploaded}
    locked = st.session_state.upload_locked_source
    if candidate and locked is not None and source_fingerprint(candidate) != locked:
        st.session_state.upload_error = "The processed upload changed. Use Choose another export to keep exports separate."
        st.session_state.uploaded_sources = {}
        return
    st.session_state.uploaded_sources = candidate
    st.session_state.upload_error = None


def _upload_controls() -> None:
    st.subheader("1. Choose CSV files")
    st.caption("Select files from one export. Uploads and results last only for this session; download what you need before leaving.")
    st.radio("Use data from", ("Bundled demo", "Replacement upload"), key="source_mode",
             horizontal=True, persist_state="session")
    if st.session_state.source_mode == "Replacement upload":
        key = f"bundle_upload_{st.session_state.upload_generation}"
        st.file_uploader("Select the export's CSV files", type="csv", accept_multiple_files=True,
                         key=key, on_change=_read_upload, args=(key,))
        if st.session_state.uploaded_sources or st.session_state.upload_error or st.session_state.upload_locked_source:
            st.button("Choose another export", key="new_upload", on_click=_new_upload)
        if st.session_state.upload_error:
            st.error(st.session_state.upload_error)


def _preview_panel(preview) -> None:
    report = preview.reporting
    if report.week_start:
        st.write(f"**Reporting week: {report.week_start:%d %b}–{report.week_end:%d %b %Y}**")
        st.caption(f"Export through {report.as_of:%A %d %b %Y}. {report.explanation}")
    st.markdown("**Files received**")
    for name in FILES:
        if name == "payroll_details.csv":
            continue
        if name in preview.bundle.tables:
            st.text(f"✓ {name} · {preview.bundle.row_counts.get(name, 0):,} rows")
        elif name in CORE_FILES:
            st.error(f"Missing or unreadable: {name} — required to load predictions.")
        elif name == "shift_notes.csv":
            st.warning("Missing or unreadable: shift_notes.csv — the explanation of why overtime happened is unavailable.")
        else:
            st.caption(f"Not available: {name} (supporting file)")
    errors = sum(issue.severity == "error" for issue in preview.issues)
    warnings = sum(issue.severity == "warning" for issue in preview.issues)
    if errors:
        st.error(f"Fix {errors} blocking file or column errors before loading.")
    elif warnings:
        st.info(f"Files can be processed with {warnings} warnings. Affected records remain flagged.")
    else:
        st.success("File checks passed.")
    if preview.issues:
        with st.expander("File and record checks", expanded=bool(errors)):
            for issue in preview.issues:
                row = f", row {issue.row}" if issue.row is not None else ""
                st.text(f"{issue.file}{row}: {issue.issue}. {issue.suggested_correction}")
    for message in preview.unavailable_outputs:
        st.warning(message)
    if report.mode == "before_wednesday":
        st.warning("This export ends before Wednesday. Supply data through Wednesday to produce the forecast.")


def _load_view(preview, policy, token: str | None, source_id: str | None) -> None:
    if st.session_state.upload_error and st.session_state.source_mode == "Replacement upload":
        return
    if preview is None:
        st.info("Choose an export to see its reporting week and file checks. Include employees.csv, shifts.csv, sites.csv and shift_notes.csv; add the other supplied CSVs if available.")
        return
    _preview_panel(preview)
    st.subheader("3. Load dashboard")
    st.caption("This replaces the active results. Changed or rejected inputs clear the previous predictions.")
    if st.button("Load dashboard", key="process_bundle", type="primary",
                 disabled=not preview.accepted or preview.reporting.mode in ("before_wednesday", "unavailable")):
        try:
            with st.spinner("Preparing employee alerts and supervisor notes…"):
                processed = process_bundle(preview, policy)
        except (ProcessingError, ValueError) as exc:
            _clear_result()
            st.error(str(exc))
        else:
            st.session_state.active_result = processed
            st.session_state.active_token = token
            if st.session_state.source_mode == "Replacement upload":
                st.session_state.upload_locked_source = source_id
            st.session_state.next_view = "Act today"
            st.session_state.selected_employee = None
            st.rerun()
    processed = st.session_state.active_result
    if processed is not None and st.session_state.active_token == token:
        with st.expander("Record checks and unmatched notes"):
            actions = tuple(action for action in processed.actions if action.kind in REVIEW_KINDS)
            st.caption("Undated records and unmatched notes cannot be assigned to a current work site or period.")
            if actions:
                st.dataframe(action_evidence_rows(actions), hide_index=True, width="stretch")
            else:
                st.write("No unresolved record checks.")


def _empty_result() -> None:
    st.warning("No predictions are active for the selected inputs. Load the export to see this week's alerts.")
    st.button("Load new data", on_click=_go, args=("Load new data",), key="empty_load")


def _recorded_hours(entry) -> None:
    snapshot = entry.snapshot
    if snapshot.no_records:
        st.write("**Recorded hours: unavailable** — no dated shifts through Wednesday; final hours and risk are not zero.")
    elif snapshot.overlapping_records:
        st.write(f"**Recorded sum: {snapshot.known_hours:.2f} h — suspect** (overlapping shifts).")
    elif entry.needs_review:
        st.write(f"**Completed recorded hours: {snapshot.known_hours:.2f} h — records need checking.**")
    else:
        st.write(f"**Completed recorded hours: {snapshot.known_hours:.2f} h** through Wednesday.")


def _employee_detail(processed: ProcessedBundle, entry) -> None:
    st.button("Back to employee list", on_click=_select_employee, args=(None,))
    st.subheader(entry.name)
    st.caption(f"{entry.employee_id} · Registered site: {entry.primary_site_name}")
    st.write(f"**{'Breach alert' if entry.forecast.will_breach else 'No breach alert'}** · Risk score {entry.forecast.risk_score:.1%}")
    _recorded_hours(entry)
    actions = employee_actions(processed, entry.employee_id)
    if actions:
        st.markdown("**Do today**")
        for action in actions:
            st.write(f"• {action.recommendation}")
    else:
        st.caption("No specific action was triggered by the available records. No alert does not guarantee a week below 55 hours.")
    if entry.review_reasons:
        st.warning("Records to check: " + "; ".join(entry.review_reasons) + ".")
    with st.expander("Hours and shifts through Wednesday"):
        st.write(f"Completed recorded hours: {entry.snapshot.known_hours:.2f} h. "
                 f"Estimated elapsed addition: {entry.snapshot.imputed_elapsed:.2f} h. "
                 f"Estimated overnight carry: {entry.snapshot.carry:.2f} h.")
        st.caption("Estimates are not confirmed worked hours. Shift sites below show where work was recorded, which can differ from the registered site.")
        shifts = employee_shift_rows(processed, entry.employee_id)
        for row in shifts:
            hours = "Unavailable" if row["Recorded hours"] is None else f'{row["Recorded hours"]:.2f} h'
            st.text(f'{row["Start date"]} · {row["Actual shift site"]}\n{row["Shift ID"]}: {row["Clock-in"]} → {row["Clock-out at cutoff"]}\n{hours} · {row["Status"]}'
                    + (" · Overlap flagged" if row["Overlap flagged"] else ""))
        if not shifts:
            st.write("No dated shift record through Wednesday.")
    with st.expander("Supervisor notes and reasons"):
        rows = employee_note_rows(processed, entry.employee_id)
        for row in rows:
            st.text(row["Note"] or "(Blank note)")
            st.caption(f'{row["Shift ID"]} · {row["Category"].replace("_", " ")} · Approval: {row["Approval in note"]}')
        if not rows:
            st.write("No uniquely linked note through Wednesday.")
        st.caption("Notes explain recorded shifts; they are not inputs to the risk score. Approval is separate from the reason for extra hours.")
    with st.expander("Risk calculation and source evidence"):
        st.write(f"Method: {entry.forecast.method_version}. Historical support: {entry.forecast.support}. "
                 f"Fallback: {entry.forecast.fallback or 'role and shift-pattern peers with personal history'}.")
        st.write("The score uses Wednesday hours and earlier completed employee-weeks. Overlaps retain their suspect sums; no repair is applied.")
        if actions:
            st.dataframe(action_evidence_rows(actions), hide_index=True, width="stretch")


def _this_week(processed: ProcessedBundle | None) -> None:
    st.title("Act today")
    if processed is None:
        _empty_result()
        return
    report = processed.ingestion.reporting
    source = "Synthetic demo" if st.session_state.source_mode == "Bundled demo" else "Uploaded export"
    st.caption(f"{report.week_start:%d %b}–{report.week_end:%d %b %Y} · Through Wed {report.week_start + timedelta(days=2):%d %b}, end of day · {source}")
    if report.mode != "wednesday_snapshot":
        st.info(f"Historical Wednesday forecast. {report.explanation}")
    if st.session_state.selected_employee:
        entry = next((row for row in processed.queue if row.employee_id == st.session_state.selected_employee), None)
        if entry is not None:
            _employee_detail(processed, entry)
            return
        st.session_state.selected_employee = None
    sites = sorted({(entry.primary_site_id, entry.primary_site_name) for entry in processed.queue}, key=lambda item: item[1])
    site_map = {f"{name} ({identifier or 'unassigned'})": identifier for identifier, name in sites}
    metrics = st.container()
    with st.expander("Filter by site or find an employee"):
        site = st.selectbox("Registered site", ["All sites", *site_map], key="site_filter", persist_state="session")
        query = st.text_input("Find an employee", placeholder="Name or employee ID", key="employee_search", persist_state="session")
    site_id = site_map.get(site)
    site_rows = filter_queue(processed, site_id)
    employees, alerts, review = queue_counts(site_rows)
    overlap = sum(entry.forecast.will_breach and entry.needs_review for entry in site_rows)
    with metrics:
        with st.container(horizontal=True, gap="small"):
            st.metric("Breach alerts", alerts, width=120)
            st.metric("Records to check", review, width=120)
        st.caption(f"{employees} employees assessed · {overlap} in both groups · {site}")
        st.caption("Alerts flag possible >55 h by Sunday, not confirmed breaches.")
    status = st.radio("Show employees", ("Breach alerts", "Records to check", "All employees"),
                      horizontal=True, key="queue_status", persist_state="session", label_visibility="collapsed")
    rows = filter_queue(processed, site_id, status, query)
    signature = (site, status, query, st.session_state.active_token)
    if st.session_state.get("table_context") != signature:
        st.session_state.table_context = signature
        st.session_state.employee_table = {"selection": {"rows": []}}
    st.caption(f"{len(rows)} employees · Select a row to view hours, notes and all actions.")
    if not rows:
        st.info("No employees match this selection. Try another list, site or search.")
    else:
        selection = st.dataframe(
            employee_table_rows(processed, rows, status), key="employee_table",
            hide_index=True, width="stretch", height=min(650, 38 + len(rows) * 60),
            row_height=80 if status == "Records to check" else 60,
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Employee": st.column_config.TextColumn(width="medium"),
                "Site": st.column_config.TextColumn(width="medium"),
                "Risk": st.column_config.NumberColumn(format="%.1f%%", width="small"),
                "Recorded h": st.column_config.NumberColumn(format="%.2f", width="small",
                    help="Completed recorded hours through Wednesday. Check the Records column for suspect or incomplete totals; estimates are in the drill-down."),
                "Records": st.column_config.TextColumn(width="medium"),
                "Do today": st.column_config.TextColumn(width="large"),
                "What to check": st.column_config.TextColumn(width="large",
                    help="All record checks for this employee. Select the row to read the full list and supporting evidence."),
                "Breach alert": st.column_config.CheckboxColumn(width="small"),
            },
        )
        if selection.selection.rows:
            _select_employee(rows[selection.selection.rows[0]].employee_id)
            st.rerun()
    with st.expander("How alerts work"):
        st.write(f"The target is final Monday–Sunday hours strictly greater than 55. Alerts start at a {processed.policy.config.threshold:.0%} risk score to prioritise catching breaches. An alert need not mean a breach is more likely than not; scores are not proven calibrated probabilities.")
        st.write("The forecast uses inputs through Wednesday, masking clock-outs after Thursday 00:00 South African time. Record-entry timing cannot be proven. Estimated hours remain separate from recorded hours.")
        st.write("On the supplied six-week exploratory replay, correlated hours caught 24 of 44 eligible breaches with 137 false alerts; the naive baseline caught 23 with 260. These are not independent validation results and exclude uncertain outcomes. The Step 8 comparison is pending.")
        st.caption(f"Method: {processed.policy.config.method_version}. Threshold policy: {processed.policy.threshold_rule}.")
    st.download_button("Download predictions.csv", processed.predictions_csv, "predictions.csv", "text/csv")
    st.caption("Download includes every registered employee, regardless of filters.")


def _note_validation(rules_version: str) -> None:
    with st.expander("How reliable are these reasons?"):
        path = ROOT / "analysis" / "evidence" / "note_validation_notes-1.0.json"
        evidence = json.loads(path.read_text()) if path.exists() else {}
        if evidence.get("status") != "reviewed" or evidence.get("rules_version") != rules_version:
            st.write("No matching completed review evidence is available for this rules version.")
            return
        for key, label in (("random_validation", "Random sample"), ("targeted_challenge", "Separate challenge sample")):
            result = evidence["splits"][key]
            st.write(f"**{label}: {result['accuracy']:.0%} agreement** across {result['matched_reviewed']} notes.")
        st.write("The saved review used the original demo notes, not this session's uploaded notes. Rules stayed frozen after review. One reviewer supplied labels; the review process was not independently observed. The random sample excluded the notebook's 170 reference notes; the challenge set is not a population estimate.")
        st.write("Nine labels disagreed: five approval-only notes were treated as client requests by the reviewer; three spelling variants were missed; one possible name was matched as ‘client’. Approval alone does not establish a request. These ambiguities can change the split.")


def _note_actions(processed: ProcessedBundle, *, historical: bool = False) -> None:
    actions = operational_actions(processed, historical=historical)
    if not actions:
        st.write("No source notes met the action rules for this period.")
        return
    for site_id in sorted({action.site_id for action in actions}):
        site = processed.ingestion.sites_by_id.get(site_id, {}).get("site_name", site_id)
        group = tuple(action for action in actions if action.site_id == site_id)
        with st.expander(f"{site} · {len(group)} checks"):
            for action in group:
                st.write(f"**{action.recommendation}**")
                st.text(action.reason)
                st.caption(f"Period: {action.period_start}–{action.period_end}")
            st.dataframe(action_evidence_rows(group), hide_index=True, width="stretch")


def _reasons(processed: ProcessedBundle | None) -> None:
    st.title("Why overtime")
    if processed is None:
        _empty_result()
        return
    if "shift_notes.csv" not in processed.ingestion.bundle.tables or any(
        message.startswith("Note classification unavailable") for message in processed.ingestion.unavailable_outputs
    ):
        st.warning("No usable shift_notes.csv was supplied. The explanation of why overtime happened is unavailable. Load an export including supervisor notes.")
        return
    report = processed.attribution
    summary = attribution_summary(processed)
    st.subheader("Overtime in completed weeks")
    if summary["start"]:
        st.caption(f'{summary["start"]:%d %b}–{summary["end"]:%d %b %Y} · This week’s partial hours are excluded.')
    if report.total_overtime_hours:
        for row in summary["rows"]:
            st.write(f'**{row["Reason"]}: {row["Hours"]:,.2f} h ({row["Share"]:.1%})**')
        st.bar_chart(summary["rows"], x="Reason", y="Hours", horizontal=True, sort=False, height=210)
        st.write(f'**{summary["rows"][2]["Share"]:.1%} of overtime has no attributable cause.** Missing or inconclusive notes remain unknown.')
    else:
        st.info("No overtime hours are available in eligible completed weeks. There is no historical split to estimate from this export.")
    st.caption(f"Associated with supervisor notes; not proven causes or billable hours. Includes {report.eligible_employee_weeks} clean employee-weeks; excludes {report.excluded_employee_weeks}. Client approval and explicit requests are distinct.")
    if summary["sites"] and summary["sites"][0].operational_associated_hours > 0:
        top = summary["sites"][0]
        st.write(f"**{top.site_name} has the largest operational-associated total: {top.operational_associated_hours:,.2f} h.**")
    with st.expander("Where operational overtime is concentrated"):
        for index, site in enumerate(summary["sites"], 1):
            st.write(f"**{index}. {site.site_name} — {site.operational_associated_hours:,.2f} operational hours**")
            st.caption(f"Client requested: {site.client_requested_hours:,.2f} h · Unknown: {site.unknown_hours:,.2f} h · Total overtime: {site.total_overtime_hours:,.2f} h")
        st.caption("These are actual shift sites. Totals describe included historical records, not this week's employee queue.")
    st.subheader("This week's supervisor reports")
    st.caption(f"Week of {processed.ingestion.reporting.week_start:%d %b %Y}, through Wednesday. Reports describe recorded shifts, not the cause of a prediction.")
    notes = current_note_rows(processed)
    counts = Counter(row["Category"] for row in notes)
    if counts:
        with st.expander(f"Browse {len(notes)} linked notes and their reasons"):
            for category, count in counts.most_common():
                st.write(f"{category.replace('_', ' ').capitalize()}: {count} notes")
            selected = st.selectbox("Read a supervisor note", range(len(notes)),
                                    format_func=lambda i: f'{notes[i]["Shift ID"]} · {notes[i]["Site"]} · row {notes[i]["Source row"]}')
            note = notes[selected]
            st.text(note["Note"] or "(Blank note)")
            st.caption(f'Reason: {note["Category"].replace("_", " ")} · Approval: {note["Approval in note"]}')
    else:
        st.write("No uniquely linked supervisor notes through Wednesday.")
    st.markdown("**Checks to make today, by actual work site**")
    _note_actions(processed)
    with st.expander("Earlier relief patterns"):
        st.caption("Historical patterns are kept separate from today's checks. Repeated reports are not proof of misconduct.")
        _note_actions(processed, historical=True)
    _note_validation(report.rules_version)
    with st.expander("Coverage, allocation and reviewer evidence"):
        st.write("Overtime is allocated after the first 45 recorded hours of each clean completed employee-week, in shift order. No-note shifts remain in the denominator. Excluded weeks are not treated as zero overtime.")
        for reason, count in report.exclusion_reasons.items():
            st.write(f"{reason.replace('_', ' ')}: {count} employee-weeks (reasons may overlap)")
        st.caption(f"Rules: {report.rules_version}. All {len(processed.note_classifications)} original source notes remain in the download, including unmatched notes.")
        st.download_button("Download note evidence CSV", processed.note_evidence_csv, "note_classification_evidence.csv", "text/csv")
    st.download_button("Download note_classifications.csv", processed.note_classifications_csv, "note_classifications.csv", "text/csv")


def main() -> None:
    _init_session()
    table_view = st.session_state.view == "Act today" and not st.session_state.selected_employee
    st.set_page_config(page_title="Jem overtime early warning", page_icon="⏱️",
                       layout="wide" if table_view else "centered")
    st.html("<style>[data-testid='stMainBlockContainer'] {padding-top: 3.5rem; padding-bottom: 2rem;}</style>")
    policy = load_policy(POLICY_PATH)
    view = st.radio("Navigate", VIEWS, key="view", horizontal=True, label_visibility="collapsed",
                    on_change=_select_employee, args=(None,))
    if view == "Load new data":
        st.title("Load new data")
        _upload_controls()
    sources = demo_sources(ROOT) if st.session_state.source_mode == "Bundled demo" else st.session_state.uploaded_sources
    preview = None
    token = None
    source_id = None
    if sources and (st.session_state.source_mode == "Bundled demo" or not st.session_state.upload_error):
        source_id = source_fingerprint(sources)
        default_preview = ingest(sources)
        if st.session_state.as_of_source != source_id:
            st.session_state.as_of_source = source_id
            st.session_state.selected_as_of = default_preview.reporting.as_of
        if view == "Load new data":
            st.subheader("2. Review detected week")
            if default_preview.reporting.as_of is not None:
                with st.expander("Advanced: replay an earlier reporting week"):
                    st.session_state.selected_as_of = st.date_input("Reporting as-of date", value=st.session_state.selected_as_of,
                                                                   key=f"as_of_{source_id[:12]}")
        as_of = st.session_state.selected_as_of
        preview = ingest(sources, as_of=as_of)
        if as_of is not None:
            token = input_fingerprint(sources, as_of, policy)
    if token != st.session_state.active_token:
        _clear_result()
    if st.session_state.source_mode == "Bundled demo" and preview is not None and preview.accepted and st.session_state.active_result is None:
        try:
            st.session_state.active_result = process_bundle(preview, policy)
            st.session_state.active_token = token
        except (ProcessingError, ValueError) as exc:
            st.error(f"Demo processing failed: {exc}")
    processed = st.session_state.active_result
    if view == "Act today":
        _this_week(processed)
    elif view == "Why overtime":
        _reasons(processed)
    else:
        _load_view(preview, policy, token, source_id)


if __name__ == "__main__":
    main()
