# Repository instructions

## Scope and sequencing

- Follow the numbered build stages supplied for this assessment; implement only
  the requested stage and preserve unrelated work.
- Preserve `ASSESSMENT.md`, the raw source files, and the reference notebooks.
- Do not add React, FastAPI, a database, Docker, a chatbot, authentication, paid
  services, or API keys.

## Data and analytical rules

- The target is final Monday–Sunday hours strictly greater than 55, using
  Wednesday-available inputs. Payment multipliers do not multiply worked hours.
- Preserve raw data; distinguish observed values, estimates and uncertain
  outcomes.
- Implement the reference correlated-hours predictor in Step 3 as the initial
  working choice. Keep it interchangeable, not deferred pending a later decision.
- Step 8 compares exactly three statistical candidates (correlated hours,
  smoothed risk table, matched historical remaining hours) with the unchanged
  naive baseline. No new model family or parameter search. Select the statistical
  candidate with highest pooled chronological F2; tie-break by higher recall,
  then fewer false alerts, then fewer total alerts, then method name. Declare this
  policy before running the comparison; show its limitations and the baseline
  result even if disappointing.
- Preserve the reference data-quality policy for the first version and disclose
  its limitations. Alternative overlap repairs are optional later sensitivity
  analyses, not a blocker or a silent change.
- Any assumption made about the data must be appended to `NOTES.md` as it is
  introduced or changed. State the assumption, rationale and effect on hours,
  predictions, classifications or evaluation. Never silently introduce a
  cleaning rule or treat estimated values as observed truth. Mark replaced
  assumptions as superseded; preserve their history.
- The UI must not contain prediction or hours-calculation logic. Keep core
  functions reusable by the app, evaluation and exports.
- Every registered employee must eventually receive one prediction. Missing
  current records do not prove zero risk.
- Manager/centre/site management does not establish client identity. Explicit
  client requests, operational causes and approval are distinct.
- Do not claim human validation or improved accuracy without actual evidence.
- No paid services or API keys. Do not log or display unused payroll identifiers.
- Implement only the requested stage; preserve unrelated work.

## Engineering guardrails

- Use Python 3.10 locally and select Python 3.10 for deployment. Keep runtime
  dependencies declared and pinned.
- Keep sensitive payroll banking, tax, and identity values out of features,
  displays, logs, tests, and diagnostics.
- Put reusable ingestion, calculation, prediction, evaluation, and export logic
  in `jem/`, not in `app.py`.
- Tests and documentation must report only checks and results that actually ran.
- Before ending any stage, report assumptions added or state that none changed.
