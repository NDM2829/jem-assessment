# Step 8 selected statistical method

**Selected: correlated hours, version `correlated-hours-1.0`.** The predeclared rule in `config/prediction_policy.toml` chooses the statistical candidate with highest pooled chronological F2, then higher recall, fewer false alerts, fewer total alerts, then method name. The rule was applied by `jem.comparison.evaluate`; naive is the unchanged comparator, not eligible for statistical-method selection. The underlying report is [`evidence/step8_comparison.json`](evidence/step8_comparison.json). The original five-method notebook remains prior exploratory evidence; this run verifies the shared application code on the same supplied export. It is not independent evidence on unseen data.

## Common six-week replay

W1 (8–14 June 2026) provides initial clean references. W2/W3 (15–28 June) seed thresholds; W4–W9 (29 June–9 August) are the six main evaluation weeks. These positions come from sorted completed historical weeks, not fixed dates in the code. Every forecast uses the strict Thursday 00:00 local cutoff for its Wednesday inputs; a given week's probability threshold uses only earlier out-of-time predictions with clean observed outcomes. The threshold grid is 0.00–1.00 by 0.01, choosing highest earlier F2, then fewer false alerts, then higher threshold. Naive keeps `A × 7/3 > 55` hours and has no probability or Brier score.

All four methods score the same 1,278 employee-weeks. Only 1,107 have clean outcome labels; 171 are excluded from the confusion metrics, but their alerts remain in review workload. There are 44 known breaches among the eligible rows.

The 171 exclusions include 118 employee-weeks flagged for missing clock-outs and 55 for overlaps; two have both flags. These are uncertain outcomes, not known non-breaches.

| Method | TP | FP | FN | Precision | Recall | F2 | All review alerts | Alerts with unknown outcome | Brier (eligible) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Correlated hours **selected** | 24 | 137 | 20 | 0.149 | 0.545 | **0.356** | 200 | 39 | 0.0349 |
| Smoothed risk table | 31 | 283 | 13 | 0.099 | 0.705 | 0.316 | 381 | 67 | 0.0368 |
| Matched historical remaining hours | 23 | 177 | 21 | 0.115 | 0.523 | 0.306 | 254 | 54 | 0.0414 |
| Naive hours projection | 23 | 260 | 21 | 0.081 | 0.523 | 0.251 | 347 | 64 | not a probability |

The selected method caught **one more** eligible breach than naive, produced **123 fewer** false alerts, and required **147 fewer** total review alerts. Its F2 was higher by 0.106. The smoothed table caught seven more breaches than correlated hours but generated 146 more false alerts and 181 more total reviews; its pooled F2 was lower. None of these clean-label metrics establish performance on the 171 excluded rows.

The selected method still missed **20 of 44** known clean breaches, and only **14.9%** of its eligible alerts were true breaches. That detection and precision limit remains unresolved even though its F2 beat the naive rule on this replay.

The selected method's weekly thresholds were 0.06, 0.09, 0.05, 0.05, 0.05, 0.05. Its weekly true positives were 3, 3, 6, 4, 4, 4 and false positives were 25, 11, 25, 26, 29, 21. This variation matters: a six-week pooled score hides changes in workload and detection. The JSON report includes every method's weekly thresholds, counts and F2.

At an equal **20 reviews per week**, correlated hours caught 19 of 44 eligible breaches, smoothed table 13, matched remainder 14 and naive 10. At **40 reviews per week**, the counts were 28, 22, 20 and 19. The budget ranks all employees, including uncertain-outcome cases, before scoring clean labels. The full 10/20/30/40 review results, with false alerts and unknown-outcome workload, are in the JSON report.

## Probability quality and support

Brier scores above are for statistical methods on eligible rows only. Broad, descriptive calibration bands in the JSON report show that correlated hours' 0.05–0.10 band averaged 0.070 predicted risk while 0.103 of those 107 eligible rows breached. Its 0.10–0.20 band averaged 0.136 versus 0.174 observed. The bands are small at higher scores and do not prove calibration. Naive's 7/3 projection is hours, so assigning it a Brier score would fabricate a probability.

Correlated hours pools each employee's earlier clean `(Wednesday hours A, remaining hours R)` weeks with role/shift-pattern peer weeks. It falls back to all other employees when fewer than ten matching peer weeks exist, and a person with no clean history uses peers only. Four peer pseudo-weeks control the personal blend; marginal variance has a 1 hour² floor, correlation is capped at ±0.95, and conditional variance is inflated by `1 + 1/(personal weeks + 4)`. Its score is a truncated-normal tail estimate of `P(final recorded hours > 55 | Wednesday inputs and earlier clean weeks)`, with a certainty override only if **completed recorded** Wednesday hours already exceed 55. This is a risk estimate, not an observed outcome or proven calibrated probability.

Inputs keep the original shift-start-date Monday–Sunday accounting, strict Wednesday cutoff, ten-peer-shift duration estimate for unavailable clock-outs, separate estimated elapsed/carry hours, and overlap flags without numeric repair. Clean labels require complete seven-day coverage and no missing/invalid duration or overlap for that employee-week. W1 reference-only elapsed hours follow the original reference reconstruction; no imputed outcome becomes a label. Missing current records do not prove zero final hours or risk. Payroll identity, bank and tax data are unused.

## Fixed deployment decision

`config/prediction_policy.toml` records `selected_method = "correlated_hours"`, `method_version = "correlated-hours-1.0"`, and **threshold 0.05**. That threshold was derived once from **1,475 eligible out-of-time forecast rows across W2–W9 (15 June–3 August 2026)**, all before the original current-week cutoff (Wednesday 12 August 2026). It matches the earlier working value; it was recomputed, not forced to match. The app, downloads and both command-line exporters read this fixed method and threshold. On a later upload, earlier clean reference statistics may refresh under the same method, while the method and threshold stay fixed until a deliberate offline re-evaluation changes the versioned config. `scripts/evaluate.py` produces a report and does not silently retune deployment.

## Limits and next evidence

The supplied weeks already informed the notebook's design and parameter choices. This chronological replay is an implementation check on reused data, not a fresh experiment; it does not prove future generalisation or an accuracy improvement over an unseen population. The 171 excluded employee-weeks still create review workload and may behave differently from the clean cases. The export has no creation timestamps, so Wednesday record availability cannot be fully verified. Overlap sums remain suspect, and plug-in duration estimates understate some uncertainty. A later assessment should compare frozen outputs on newly received complete weeks, record resolution of uncertain rows, and audit calibration and workload without tuning on those same outcomes.
