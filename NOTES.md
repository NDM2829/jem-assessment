# Assessment notes

## Data assumptions

- I count clock-in to clock-out time towards a Monday–Sunday total. A breach means **more than 55 hours**. The data does not show unpaid breaks, so I do not deduct them.
- I assign an overnight shift to the day it started. This matches the supplied weekly totals, but can place Sunday-night hours in a different week from a midnight split.
- For the Wednesday forecast, I stop at Thursday 00:00. I estimate missing shift durations from earlier shifts, but keep estimated hours separate from recorded hours. I flag overlaps rather than guessing which record is correct.
- I use only complete, clean recorded weeks to check predictions. **171 employee-weeks** had uncertain outcomes and were excluded from the main comparison. I also assume the employee register did not change during the historical period, because it has no effective dates.
- I classify work as *client-requested* only when a note says the client requested it. A note linked to overtime does not prove what caused those hours or who should pay for them.

The [assumption log](evidence/assumption_log.md) records the detailed choices and limitations.

## How I checked the notes

I froze the sorting rules at notes-1.0 before validation so I could test the rules I had actually built rather than adjust them to match the review labels. I then compared the assigned category against one reviewer’s hand-labelled category, first on 100 randomly sampled notes and separately on 20 deliberately difficult cases. I also checked that each shift ID and original note matched the source data.

The rules agreed with my review on 93/100 random notes and 18/20 difficult notes. More importantly, the check showed where the rule-based approach was weak. Most disagreements came from ambiguous wording or language the rules had not anticipated rather than completely wrong categories. The main problem was distinguishing a client explicitly requesting extra work from merely approving it. The rules also missed spelling variants and, in one case, interpreted a person’s name (“Clint”) as “client”.

This gave me reasonable confidence that the rules capture the common note patterns consistently, while also showing that they are brittle around ambiguous language, typos and unseen wording. Those errors can change how overtime is grouped by stated reason, but they do not change the recorded hours or breach predictions.

The [labels](evidence/note_validation_review_completed.csv) and [results](analysis/evidence/note_validation_notes-1.0.json) preserve the comparison and disagreements. I kept the reported rules unchanged after this check.The random sample excluded notes already used when developing the rules, and the difficult set was intentionally challenging, so I kept the two results separate rather than combining them into one accuracy figure. One reviewer is not definitive ground truth, and any revised rules would need a fresh independently labelled sample to test whether they actually improve.

## What a trained model could add

My correlated-hours method mainly learns how Wednesday hours relate to the hours an employee is likely to work for the rest of the week, using their own history where available and similar employees as a fallback. A trained model could learn more complex relationships between factors such as site, role, shift pattern, earlier-week behaviour and potentially the supervisor notes, rather than relying mainly on this hours relationship.

With only a couple of hundred employees, I would be careful not to mistake overfitting for improvement. I would freeze the model and decision threshold before testing it on later, unseen weeks, keep all information from the future out of the features, and compare it against the same naive baseline using recall, F2, false alerts and review workload. I would only trust an improvement if it continued on genuinely new weeks that were not used to choose the model or tune its parameters.
