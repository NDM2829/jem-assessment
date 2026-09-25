# Jem overtime early warning

This repository is being built in ordered assessment stages. The current
deliverable is **Step 1 only**: a runnable Streamlit shell with no
analytical output. Data ingestion is planned for Step 2; the first genuine
correlated-hours predictor is planned for Step 3.

The supplied `ASSESSMENT.md`, synthetic CSV files, and reference notebooks are
preserved as source material. The application does not read or display them yet.

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

Run the Step 1 check with:

```bash
source .venv/bin/activate
python -m pytest
```

## Current architecture

- `app.py`: presentation-only Streamlit entrypoint
- `jem/`: reusable application modules; currently exposes stage status only
- `config/prediction_policy.toml`: predeclared initial method and Step 8 policy
- `tests/`: focused automated checks

There is no React app, API server, database, container, chatbot, authentication
system, paid service, or API key. Prediction and hours logic must remain outside
the UI as later stages add it.

## Current limitations

This shell makes no claim about overtime hours, likely breaches, model quality,
note causes, or human validation. It does not yet load a new export. Those are
explicitly later checkpoints.
