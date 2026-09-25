# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 5**: deployment preparation for the small Streamlit
dashboard around the shared correlated-hours predictor. It opens the bundled
synthetic export by default, accepts a replacement CSV bundle, and offers a
predictions download.

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
- `jem/exports.py`, `scripts/export_submission.py`: checked submission CSV and manifest
- `jem/workflow.py`: session-safe processing, queue facts and current shift evidence
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

The dashboard displays current-week hours, predictions and quality flags. Note
classification and human note validation remain pending in Step 6. The three-model
comparison remains pending in Step 8; the working correlated-hours predictions
stay available. `ingest` accepts a replacement mapping of filenames to paths,
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
