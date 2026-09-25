# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 2**: a shared CSV ingestion and validation pipeline.
The Streamlit page remains a shell. The first correlated-hours predictor is
planned for Step 3, and the browser upload workflow for a later stage.

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
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

No overtime hours, predictions, note classifications or human validation are
produced yet. `ingest` accepts a replacement mapping of filenames to paths,
bytes or browser file objects. Each call is isolated; callers should discard
old results when a replacement is rejected. Row counts exclude payroll because
its contents are deliberately unread. The reporting context gives the first
and last valid shift dates, selected week, snapshot mode and historical fallback
state. The browser interface for uploading a bundle is a later checkpoint.
