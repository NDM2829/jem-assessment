"""Reference weighted historical remaining-hours blocks under fixed distances."""

from __future__ import annotations

import math

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import Forecast, PredictorConfig, ProcessingError, forecast_period
from jem.predictors.reference_stats import clean_before, groups, prior_usual_hours, usual_hours

DAY_MISMATCH_PENALTY = 2.0
HOURS_BANDWIDTH = 8.0
USUAL_HOURS_BANDWIDTH = 5.0


def _weighted_tail(donors: tuple[HistoricalRow, ...], row: Snapshot, current_usual: float,
                   states: dict[tuple[str, object], float | None]) -> tuple[float, float]:
    if not donors:
        raise ProcessingError("Matched remainder needs at least one clean earlier donor.")
    distances = []
    for donor in donors:
        distance = abs(donor.snapshot.days - row.days) * DAY_MISMATCH_PENALTY
        distance += abs(donor.A - row.A) / HOURS_BANDWIDTH
        donor_usual = states[(donor.snapshot.employee_id, donor.snapshot.week_start)]
        if donor_usual is not None:
            distance += abs(donor_usual - current_usual) / USUAL_HOURS_BANDWIDTH
        distances.append(distance)
    closest = min(distances)
    weights = [math.exp(-(distance - closest)) for distance in distances]
    total = sum(weights)
    weights = [weight / total for weight in weights]
    risk = sum(weight for weight, donor in zip(weights, donors) if donor.R > 55 - row.A)
    effective_n = 1 / sum(weight * weight for weight in weights)
    return risk, effective_n


def predict(snapshot: tuple[Snapshot, ...], history: tuple[HistoricalRow, ...],
            config: PredictorConfig) -> tuple[Forecast, ...]:
    if not snapshot:
        return ()
    week = snapshot[0].week_start
    if any(row.week_start != week for row in snapshot):
        raise ValueError("Predict one reporting week at a time.")
    reference = clean_before(history, week)
    if not reference:
        raise ProcessingError("No clean earlier historical weeks support matched remaining hours.")
    states = prior_usual_hours(history, week, config)
    results = []
    for row in snapshot:
        own, peer, fallback = groups(row, reference, config)
        usual = usual_hours(row, reference, config)
        peer_risk, peer_ess = _weighted_tail(peer, row, usual, states)
        if own:
            own_risk, own_ess = _weighted_tail(own, row, usual, states)
            personal_weight = len(own) / (len(own) + config.personal_prior_weeks)
            risk = personal_weight * own_risk + (1 - personal_weight) * peer_risk
            effective_n = 1 / (personal_weight ** 2 / own_ess + (1 - personal_weight) ** 2 / peer_ess)
        else:
            personal_weight = 0.0
            effective_n = peer_ess
            risk = peer_risk
        if row.known_hours > 55:
            risk = 1.0
        results.append(Forecast(row.employee_id, risk >= config.threshold, risk, week, forecast_period(week),
                                config.threshold, config.method_version,
                                f"personal_weeks={len(own)};peer_weeks={len(peer)};effective_donors={effective_n:.2f}",
                                fallback,
                                {"known_hours": row.known_hours, "estimated_elapsed": row.imputed_elapsed,
                                 "overnight_carry": row.carry, "suspect_overlap": bool(row.overlapping_records),
                                 "unknown_records": row.unknown_records, "missing_clockouts": row.missing_clockouts,
                                 "future_end_masked": row.future_end_masked, "no_records": row.no_records,
                                 "usual_hours": usual, "wednesday_days": row.days,
                                 "personal_weight": personal_weight, "effective_donors": effective_n,
                                 "peer_donors": len(peer), "personal_donors": len(own),
                                 "day_mismatch_penalty": DAY_MISMATCH_PENALTY,
                                 "hours_bandwidth": HOURS_BANDWIDTH,
                                 "usual_hours_bandwidth": USUAL_HOURS_BANDWIDTH}))
    return tuple(results)
