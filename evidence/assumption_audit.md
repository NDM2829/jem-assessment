# Assumption-to-code audit

Checked the preserved [full history](assumption_log.md) against the current shared implementation for the final assessment audit. No data policy was changed in this step.

| Material active rule | Implementation checked | Audit result |
|---|---|---|
| Shift-start Monday–Sunday accounting, less-than-24-hour overnight, no break subtraction, strict >55 | `jem/hours.py`, `jem/features.py` | Matches. Sunday overnight is assigned wholly to the start week; calendar-time work can differ. |
| Thursday 00:00 local snapshot and future-end masking; estimated time separate from observed | `jem/hours.py`, `jem/features.py` | Matches. Missing source creation timestamps prevent proving that every row was present on Wednesday. |
| Ambiguous IDs, missing/invalid times and overlaps remain uncertain; no numeric overlap repair | `jem/pipeline.py`, `jem/features.py` | Matches. Suspect recorded sums are still displayed with flags; they are not certified hours. |
| Seven represented shift dates and clean employee-week outcomes, with no imputed label | `jem/features.py` | Matches. The current week is reserved. The static current register is reused historically because effective-dated membership is unavailable. |
| Earlier clean reference, fixed selected correlated method and threshold; peer-only new-employee fallback | `jem/predictors/correlated_hours.py`, `jem/workflow.py`, `config/prediction_policy.toml` | Matches. W1 has an inherited special reference-only reconstruction from eventual completed elapsed hours at the cutoff; this limits a literal as-of claim for W1 and is disclosed in `NOTES.md`. No evaluated week's threshold uses its own outcomes. |
| Explicit client request distinct from manager instruction/approval; conflicting or unmatched notes remain uncertain | `jem/notes.py`, `jem/attribution.py` | Matches. Source note text is retained and multiple linked notes do not duplicate worked hours. Association after 45 hours is not causal or billable proof. |
| Source-linked actions and conditional remaining-hours allowance | `jem/actions.py`, `jem/workflow.py` | Matches. Suspect current records prompt review rather than an invented safe allowance. |
| Payroll fields unused | `jem/io.py`, export scripts and `.gitignore` | Matches for processing and current deployment tree; an earlier Git history may still contain the raw payroll file. |

Superseded decisions remain in the full log: the earlier shift-date-only Wednesday availability; the notebook's site-manager-as-client inference; pending human note-review status; and Step 3's pre-comparison method status. The Step 8 code selected the same numeric method and threshold under the declared rule. The review sheet reproduced the saved 100/20 metrics exactly; its one-reviewer and sampling limits remain active.
