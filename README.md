# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 7**: source-linked manager actions, alongside note
classification, historical overtime association and the working correlated-hours dashboard. It opens the
bundled synthetic export by default, accepts a replacement CSV bundle, and
offers predictions and note-classification downloads.

The supplied `ASSESSMENT.md` and reference notebooks are preserved as source
material. The demo export loads through `jem.pipeline.ingest_demo`. The unused
payroll CSV remains in the local raw originals but is excluded from the Git
deployment tree; the loader accepts its absence and never reads its contents.

## Runtime

- Python 3.10.4 (the installed local interpreter reused for this project)
- Streamlit 1.64.0

For Streamlit Community Cloud, select **Python 3.10** in Advanced settings so
deployment uses the same Python minor version as local development. The local
patch version is recorded in `.python-version`. Runtime packages are pinned in
`requirements.txt`; `requirements-dev.txt` is for local tests only.
Python 3.10 remains supported for this deployment but is scheduled to reach
end of life in October 2026. Recheck Cloud support and test a Python upgrade
before a deployment after that date.

## Streamlit Community Cloud deployment

After committing and pushing this preparation to GitHub, sign in to
[Streamlit Community Cloud](https://share.streamlit.io/) and connect the GitHub
account with access to the repository. Create an app from an existing GitHub
repository with these settings:

| Setting | Value |
| --- | --- |
| Repository | `NDM2829/jem-assessment` |
| Branch | `main` |
| Main file path | `app.py` |
| Python version (Advanced settings) | `3.10` |
| Dependencies | Root `requirements.txt` (automatically detected) |

The repository is currently **private**. Authorize Community Cloud to access
this private repository. Decide whether the deployed app should remain private
(and invite reviewers) or be public; the app's visibility is a separate
setting. Community Cloud currently permits one private app per account. No
secrets are needed, and the free Community Cloud service is
sufficient. Check the deployed app yourself before sharing its generated URL;
no public URL has been verified here. See the official [deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[dependency guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies),
and [sharing guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app).

The published demo includes the six CSV files used by the application. The
unused `payroll_details.csv` is ignored and absent from the current Git tree;
the raw original is unchanged on the local machine. Because the file was
previously tracked, it remains in prior Git history. Keep the repository
private unless that history has been reviewed before a visibility change.
Notebook files may stay in the repository as references, but the app neither
imports nor executes them. Runtime paths resolve from the repository files,
so the demo opens without uploads.

Uploads and processed results live only in the active Streamlit session. They
are lost on browser refresh, a new tab, server restart or host hibernation;
the demo reloads on a fresh session. Community Cloud may hibernate an app after
12 hours without traffic and wake it on a visit. Uploaded data is not durably
stored; download anything needed before ending the session. See Streamlit's
[session-state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
and [app-management](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
documentation.

## Install and run locally

From the repository root:

```bash
/Library/Frameworks/Python.framework/Versions/3.10/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m streamlit run app.py
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`).

Run the current checks with:

```bash
source .venv/bin/activate
python -m pytest
```

## Current architecture

- `app.py`: presentation-only Streamlit entrypoint
- `jem/io.py`: shared lossless CSV reader for demo paths, upload objects and export scripts
- `jem/pipeline.py`: validation, safe unique-ID lookups and reporting context
- `jem/hours.py`, `jem/features.py`: strict Wednesday snapshots and separate observed outcomes
- `jem/predictors/`: correlated-hours method and naive hours comparator
- `jem/evaluation.py`: offline chronological replay and threshold selection
- `jem/exports.py`, `scripts/export_assessment.py`: checked submission CSVs and prediction manifest
- `jem/workflow.py`: session-safe processing, queue facts and current shift evidence
- `jem/notes.py`, `jem/attribution.py`: versioned note rules and clean historical overtime association
- `jem/actions.py`: deterministic recommendations with source file, row and key evidence
- `jem/note_evaluation.py`: exact-text human-review metrics, separate by sample split
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

The dashboard displays current-week hours, predictions, quality flags, source
note classifications, historical overtime association and record-linked actions. Human note validation
has been completed for `notes-1.0` on one sheet prepared without classifier
labels; the review process itself was not independently observed. Known misses
are reported in `NOTES.md`, and the rules were left unchanged after review.
The supplied notebook's AI-reference agreement is not human accuracy. The three-model
comparison remains pending in Step 8; the working
correlated-hours predictions stay available. `ingest` accepts a replacement mapping of filenames to paths,
bytes or browser file objects. Each call is isolated; callers should discard
old results when a replacement is rejected. Row counts exclude payroll because
its contents are deliberately unread. The reporting context gives the first
and last valid shift dates, selected week, snapshot mode and historical fallback
state. Browser uploads and their results live only in the current Streamlit
session; they are not durably stored. A changed upload must be started as a new
replacement bundle. Filter changes reuse the processed result. Input, reporting
date and policy changes invalidate it; replacement uploads require processing
again. Browser downloads are generated in memory and do not change the root
assessment export.

Run `python scripts/export_assessment.py` to regenerate both root assessment
CSVs, `predictions.csv` and `note_classifications.csv`, and the
`predictions_manifest.json` from the bundled synthetic export. The prediction CSV contains
exactly `employee_id,will_breach,risk_score`. The manifest records input hashes,
the reporting week, cutoff, fixed threshold, method version and quality counts.
The fixed threshold is 0.05, selected from earlier eligible out-of-time
forecasts under the predeclared F2 grid rule. The six-week shared-code replay
matches the notebook's 24/44 caught and 137 false alerts for correlated hours,
versus 23/44 and 260 for the naive comparator. These are exploratory replay
results on the supplied dataset, not new independent validation.

The note CSV contains exactly `shift_id,category,note` and one row per original source note.
The app download uses the same serializer. Original note text, blanks and
literal `n/a` survive the CSV round trip. A separate reviewer evidence download
keeps normalized matching text, typo corrections, client-request evidence,
approval and review flags without adding columns to the submission CSV.

The original `note_validation_review.csv` remains a blank template. The
completed review is kept locally outside Git; the non-identifying metrics are
saved under `analysis/evidence/`. All 120 labels matched the current shift IDs
and exact original note text. Against those human labels, frozen `notes-1.0`
agreed on 93/100 random notes and 18/20 targeted challenge notes. The nine
disagreements comprise five approval-only notes labelled
client-requested by the reviewer but left unknown by the rules, three missed
spelling variants, and one possible person name fuzzy-matched to `client`.
These misses and the single-reviewer limitation are disclosed rather than
tuned away. To reproduce the metrics locally, run
`python scripts/evaluate_notes.py --review PATH_TO_COMPLETED_REVIEW.csv`.
The script keeps random and targeted challenge results separate and accepts
only matching shift IDs and exact original text. It never fills human labels.
The historical attribution assigns overtime after
45 recorded hours in chronological shift order for clean completed weeks only.
It includes no-note hours in the unknown denominator and uses actual shift
sites. These are associations, not proven causes or billable hours.

Recommendations are generated from forecast alerts, current shift-quality flags
and uniquely linked notes. Each has a reason and source file/row/key evidence.
The **Load new data** view shows unresolved current records and unmatched
notes. Employee details show their alert and record checks; **Why overtime**
shows site relief patterns and current equipment/client-scope checks. Relief
patterns mean at least two distinct shifts at one actual site in a Monday–Sunday
period. A numeric allowance before 55 appears only for usable current recorded
hours; estimates are shown separately. Actions never infer a roster change,
future shift, misconduct finding, monetary saving or billing entitlement.
The first-version overlap and duration policies remain in force. Optional
sensitivity investigations are listed in `NOTES.md` and have not changed outputs.

## Dashboard walkthrough

1. Open **Act today**. The week and Wednesday cutoff come from the export.
   Separate counts show breach alerts and employees needing record checks, with
   their overlap stated explicitly. The default list contains breach alerts.
2. **Breach alerts** shows every alert in one sortable table, with the employee,
   registered site, risk, recorded hours, record status and next action.
   **Records to check** lists every employee needing review and all their specific
   checks. **All employees** shows the complete register. There is no pagination;
   site filtering and search narrow the table when needed. Downloads always
   contain every employee.
3. Select a table row to open the employee drill-down. Record
   corrections appear before any remaining-hours allowance. Shifts, notes,
   estimates and source rows are expandable. Return with **Back to employee list**.
4. Open **Why overtime** for the historical client-requested / operational /
   unknown hours split, the largest operational concentration and ranked actual
   work sites. The unknown share and excluded coverage remain visible. Current
   supervisor reports and site checks are separate from earlier relief patterns.
   **How reliable are these reasons?** reads the saved, version-matched demo
   review metrics and discloses the nine disagreements and review limitations;
   it does not claim validation of uploaded notes.
5. Open **Load new data**, select **Replacement upload**, and choose the CSVs
   from one export. Review the automatically detected week and file checklist,
   then select **Load dashboard**. Success returns directly to **Act today**.
   An earlier reporting date is available in the advanced expander. Changed,
   cleared or rejected inputs invalidate active results. Use **Choose another
   export** to replace a processed upload; files from separate exports are not
   combined. Uploads last only for this session.
6. Download `predictions.csv` from **Act today** and `note_classifications.csv`
   from **Why overtime**. These do not overwrite the repository's exports.

The employee tables use the available screen width and support scrolling and
sorting. The drill-down keeps detailed evidence in expanders. This
presentation update retains the Step 7 predictor, classifications, hours and
quality policy; it does not implement the pending Step 8 comparison.
