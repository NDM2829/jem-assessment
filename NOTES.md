# Assessment notes

## Data assumptions

- I count clock-in to clock-out time towards a Monday–Sunday total. A breach means **more than 55 hours**. The data does not show unpaid breaks, so I do not deduct them.
- I assign an overnight shift to the day it started. This matches the supplied weekly totals, but can place Sunday-night hours in a different week from a midnight split.
- For the Wednesday forecast, I stop at Thursday 00:00. I estimate missing shift durations from earlier shifts, but keep estimated hours separate from recorded hours. I flag overlaps rather than guessing which record is correct.
- I use only complete, clean recorded weeks to check predictions. **171 employee-weeks** had uncertain outcomes and were excluded from the main comparison. I also assume the employee register did not change during the historical period, because it has no effective dates.
- I classify work as *client-requested* only when a note says the client requested it. A note linked to overtime does not prove what caused those hours or who should pay for them.

The [assumption log](evidence/assumption_log.md) records the detailed choices and limitations.

## How I checked the notes

I froze the sorting rules and compared them with one reviewer’s labels for 100 randomly sampled notes and 20 deliberately difficult notes. The rules agreed on **93/100** and **18/20**, respectively. Five disagreements involved notes saying the client *approved* extra hours: the reviewer called these client requests, while my rules require an explicit request. Three misses involved spelling variants, and one mistook “Clint” for “client.”

The [labels](evidence/note_validation_review_completed.csv) and [results](analysis/evidence/note_validation_notes-1.0.json) show those disagreements. One reviewer is not definitive ground truth, and the difficult notes are not a measure of overall accuracy.

## What a trained model could add

My hours model already learns from earlier weeks how Wednesday hours relate to the hours still to come. A more flexible model might learn patterns between work schedules and breaches that this approach misses. A trained text model might handle varied wording and spelling better than fixed rules. Neither can recover a reason that was never recorded.

With roughly 200 employees, I would freeze the method and alert threshold, then test on **newer weeks** using only information available by Wednesday. I would compare it with the simple hours baseline and report missed breaches, false alerts, probability quality and the manager’s review workload. I would resolve uncertain outcomes rather than count them as non-breaches. I would also hold out employees separately to test how well the model works for people it has never seen.
