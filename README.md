# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 3**: shared hours features, a first correlated-hours
predictor, an offline chronological replay and a real current-week export.
The Streamlit page remains a shell; the browser upload workflow is a later stage.

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
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

The dashboard does not yet display hours, predictions or note classifications.
No human note validation has been performed. `ingest` accepts a replacement mapping of filenames to paths,
bytes or browser file objects. Each call is isolated; callers should discard
old results when a replacement is rejected. Row counts exclude payroll because
its contents are deliberately unread. The reporting context gives the first
and last valid shift dates, selected week, snapshot mode and historical fallback
state. The browser interface for uploading a bundle is a later checkpoint.

Run `python scripts/export_submission.py` to regenerate `predictions.csv` and
`predictions_manifest.json` from the bundled synthetic export. The CSV contains
exactly `employee_id,will_breach,risk_score`. The manifest records input hashes,
the reporting week, cutoff, fixed threshold, method version and quality counts.
The fixed threshold is 0.05, selected from earlier eligible out-of-time
forecasts under the predeclared F2 grid rule. The six-week shared-code replay
matches the notebook's 24/44 caught and 137 false alerts for correlated hours,
versus 23/44 and 260 for the naive comparator. These are exploratory replay
results on the supplied dataset, not new independent validation.
