# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 4**: a small Streamlit dashboard around the shared
correlated-hours predictor. It opens the bundled synthetic export by default,
accepts a replacement CSV bundle, and offers a predictions download.

The supplied `ASSESSMENT.md`, synthetic CSV files, and reference notebooks are
preserved as source material. The demo export loads through `jem.pipeline.ingest_demo`.

## Runtime

- Python 3.10.4 (the installed local interpreter reused for this project)
- Streamlit 1.64.0

For Streamlit Community Cloud, select **Python 3.10** in Advanced settings so
deployment uses the same Python minor version as local development. The local
patch version is recorded in `.python-version`.

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
- `jem/exports.py`, `scripts/export_submission.py`: checked submission CSV and manifest
- `jem/workflow.py`: session-safe processing, queue facts and current shift evidence
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

The dashboard displays current-week hours, predictions and quality flags. Note
classification and human note validation remain pending. `ingest` accepts a replacement mapping of filenames to paths,
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

Run `python scripts/export_submission.py` to regenerate `predictions.csv` and
`predictions_manifest.json` from the bundled synthetic export. The CSV contains
exactly `employee_id,will_breach,risk_score`. The manifest records input hashes,
the reporting week, cutoff, fixed threshold, method version and quality counts.
The fixed threshold is 0.05, selected from earlier eligible out-of-time
forecasts under the predeclared F2 grid rule. The six-week shared-code replay
matches the notebook's 24/44 caught and 137 false alerts for correlated hours,
versus 23/44 and 260 for the naive comparator. These are exploratory replay
results on the supplied dataset, not new independent validation.

## Dashboard walkthrough

1. Open **This week**. Review the reporting period, separate breach-alert and
   data-review counts, and filter the employee queue by registered primary site.
2. Select an employee to see the genuine risk, support/fallback, completed and
   estimated hours, quality flags, and shifts with their actual work sites.
3. Open **Overtime reasons** to see the pending Step 6 status. No note reason or
   client-request attribution is claimed yet.
4. Open **Load data & checks**, choose **Replacement upload** in the sidebar,
   then select one same-format CSV bundle. Check row counts, date coverage and
   structured issues before pressing **Process bundle**. To replace that upload,
   click **Start a new replacement upload** first. Rejected inputs clear results.
5. Return to **This week** to review the replacement and download its
   `predictions.csv`. This download never overwrites the repository's original
   `predictions.csv`.
