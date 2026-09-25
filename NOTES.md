# Notes and assumption history

## Step 1 — runnable shell

No data assumptions were introduced or changed in this step. The application
does not yet load data, calculate hours, predict breaches, classify notes, or
evaluate outcomes, so the reference notebooks' data policies have not been
silently activated as application behaviour.

Runtime and project-structure choices are documented in `README.md`; they do not
affect hours, predictions, classifications, or evaluation.

## Step 2 — CSV ingestion and validation

- **Reporting selection:** The default as-of date is the latest valid shift **start** date, and its Monday–Sunday week is the reporting week. An explicit as-of date selects its own week. Rationale: overnight clock-outs and the machine's current date must not move the reporting period. Effect: later hours and predictions will be tied to the selected shift-start week; the loader does not compute either yet.
- **Snapshot labeling:** A selection before Wednesday is an incomplete snapshot. A completed selected week with later data is a historical replay; dates after Wednesday require a Wednesday cutoff in later prediction code. Rationale: these exports do not represent a live, complete Wednesday forecast. Effect: evaluation and prediction displays must use the recorded mode and cutoff, never silently treat later records as Wednesday inputs.
- **Historical availability:** One prior Monday–Sunday shift-date span is the minimum signal for a historical method. If absent, ingestion records `fallback_required`. A date span alone does not prove every worked shift is present. Rationale: records can omit genuine no-work days, so exact day-by-day completeness cannot be inferred. Effect: later prediction code must disclose fallback or missing historical coverage; no accuracy claim follows from the span.
- **Identifiers and joins:** IDs remain literal strings. Blank or repeated IDs stay in raw rows, but repeated keys are excluded from unique lookup indexes, including when duplicate rows are identical. Rationale: selecting one authoritative row without evidence could multiply or misattribute joins. Effect: affected shift hours and notes cannot be safely attributed until corrected; retained raw rows remain available for review. No estimate is treated as observed.
- **Unmatched notes:** Every original note and blank or literal `n/a` is retained. A note gains shift, employee and site attribution only through one unique shift and resolvable employee and site. Rationale: text can still be classified without a valid join. Effect: classifications can include unmatched text, while later site/employee hour attribution must exclude it.
- **Format and missing values:** Dates use `YYYY-MM-DD`, times use 24-hour `HH:MM`, numeric hours are finite and nonnegative, and exported breach flags accept true/false, yes/no or 1/0. Invalid row values and missing clock-outs are review warnings, not fabricated values or whole-export failures. Rationale: retain imperfect source evidence. Effect: later hours, predictions and evaluation must exclude or flag affected records under the reference data-quality policy; this step does not calculate outcomes.
- **Auxiliary files:** Employees, shifts and sites are required to process employee hours. Missing or malformed shift notes, holidays or weekly summary disable their dependent outputs without blocking core ingestion. Payroll details are accepted as an unused file and never parsed or retained. Rationale: these sources serve different deliverables and payroll includes sensitive unused values. Effect: missing notes prevent classification, missing holidays remove holiday context, and missing weekly summaries prevent exported-summary comparison; payroll absence or extra fields have no effect on predictions.
