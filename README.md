# Jem overtime early warning

A Streamlit ops dashboard for the synthetic [assessment brief](ASSESSMENT.md). It lists Wednesday breach alerts, records to check and every registered employee; each row opens source-linked hours, notes and manager actions. **The supplied hosted URL could not be verified from this environment**, so no live-dashboard link is asserted here.

## Run and load data

Use Python 3.10 (`.python-version`); dependencies are pinned. From the repository root:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m streamlit run app.py
```

The bundled synthetic export opens by default. For a later same-format export, open **Load new data → Replacement upload**, select the CSV files from *one* export (`employees.csv`, `shifts.csv`, `sites.csv`, `shift_notes.csv`; holidays and weekly summary are optional), check the detected week, then choose **Load dashboard**. Use **Choose another export** before replacing a processed upload. The dashboard offers `predictions.csv` and `note_classifications.csv` downloads. Missing notes leave the cause view unavailable; a bundle missing a core file is rejected. Uploads and results are held only in the current Streamlit session, not saved on the server; download outputs before refresh, a new tab or server restart. The repository-root CSVs always represent the original supplied export, not a browser upload. A [labelled synthetic replacement check](evidence/upload_replay.md) demonstrates the week, roster, notes and downloads changing without code edits.

## Reproduce outputs and checks

```bash
source .venv/bin/activate
python scripts/export_assessment.py
python scripts/evaluate.py
python scripts/evaluate_notes.py --review evidence/note_validation_review_completed.csv
python -m pytest -q -p no:cacheprovider
```

`export_assessment.py` recreates the two required root CSVs and `predictions_manifest.json` from `data/demo/`. For a separate export without replacing the root files, use `python scripts/export_assessment.py --data-dir PATH --output-dir OUTPUT_DIR`. The evaluation report is [step8_comparison.json](analysis/evidence/step8_comparison.json); the [selected-method explanation](analysis/SELECTED_METHOD.md) includes thresholds, calibration and review budgets. The completed note labels and [metrics](analysis/evidence/note_validation_notes-1.0.json) reproduce the disclosed one-reviewer check. A [five-minute video checklist](evidence/video_checklist.md) covers the live walkthrough; no video link has been supplied.

## How it works

`jem/io.py` and `jem/pipeline.py` validate a bundle; `jem/hours.py` and `jem/features.py` build Wednesday snapshots and separate clean outcomes. `jem/predictors/` scores the fixed statistical candidates; `jem/workflow.py` supplies the selected predictor, full employee queue and app/export parity. `jem/notes.py`, `jem/attribution.py` and `jem/actions.py` provide source-linked reasons and operational checks. `jem/comparison.py` runs the chronological common replay. `app.py` presents these shared results without calculating predictions or hours.

The selected deployment is **correlated hours**, with a fixed **0.05** alert threshold in [config](config/prediction_policy.toml). Earlier completed clean history may refresh its reference statistics on a new upload; the method and threshold do not change until explicit offline re-evaluation. On the reused six-week synthetic replay, it caught **24/44** eligible breaches with **137** false alerts (F2 **0.356**); the naive Wednesday-hours × 7/3 baseline caught **23/44** with **260** false alerts (F2 **0.251**). Another **171** employee-weeks had uncertain outcomes and were excluded from confusion counts. These weeks informed method development, so this is a shared-implementation check, not independent evidence of future accuracy. Scores are historical statistical estimates, not proven calibrated probabilities. Overlap sums remain suspect and missing records are not zero-risk evidence. Note reasons are associations, not confirmed causes or billable hours. See [NOTES.md](NOTES.md) and the full [assumption history](evidence/assumption_log.md).

## Publishing status

The configured Git remote is `NDM2829/jem-assessment`, branch `main`, entrypoint `app.py`; deployment should use Python 3.10 and root `requirements.txt`. This environment could not resolve the supplied Streamlit or GitHub hosts, so current live access, repository visibility and the latest deployed revision remain **unverified**. The account owner must push these changes, confirm [Community Cloud repository access](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account) and the Python setting, then check the updated app (or publish it if absent). Community Cloud normally updates an existing app from its GitHub source; [changing Python after deployment requires redeployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python). Open the default dashboard and a replacement upload, then supply working dashboard, repository-access and five-minute video links. No secrets or paid services are required. The unused payroll file is ignored by processing and excluded from the deployment tree; its raw local original and prior Git history have not been altered.
