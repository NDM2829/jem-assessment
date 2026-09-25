"""Reference smoothed breach-risk table by past-only usual-hours band and Wednesday days."""

from __future__ import annotations

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import Forecast, PredictorConfig, ProcessingError, forecast_period
from jem.predictors.reference_stats import clean_before, groups, prior_usual_hours, usual_hours

TABLE_PRIOR_ROWS = 30.0


def _band(hours: float | None) -> int | None:
    if hours is None:
        return None
    return 0 if hours <= 40 else 1 if hours <= 45 else 2 if hours <= 50 else 3


def predict(snapshot: tuple[Snapshot, ...], history: tuple[HistoricalRow, ...],
            config: PredictorConfig) -> tuple[Forecast, ...]:
    if not snapshot:
        return ()
    week = snapshot[0].week_start
    if any(row.week_start != week for row in snapshot):
        raise ValueError("Predict one reporting week at a time.")
    reference = clean_before(history, week)
    if not reference:
        raise ProcessingError("No clean earlier historical weeks support the smoothed risk table.")
    donor_usual = prior_usual_hours(history, week, config)
    results = []
    for row in snapshot:
        own, peer, fallback = groups(row, reference, config, allow_global_fallback=True)
        usual = usual_hours(row, reference, config)
        band = _band(usual)
        cell = tuple(past for past in reference
                     if _band(donor_usual[(past.snapshot.employee_id, past.snapshot.week_start)]) == band
                     and past.snapshot.days == row.days)
        broader_rows = peer or reference
        broader = sum(bool(past.outcome.target_will_breach) for past in broader_rows) / len(broader_rows)
        risk = (sum(bool(past.outcome.target_will_breach) for past in cell)
                + TABLE_PRIOR_ROWS * broader) / (len(cell) + TABLE_PRIOR_ROWS)
        if row.known_hours > 55:
            risk = 1.0
        results.append(Forecast(row.employee_id, risk >= config.threshold, risk, week, forecast_period(week),
                                config.threshold, config.method_version,
                                f"personal_weeks={len(own)};peer_weeks={len(peer)};cell_weeks={len(cell)}",
                                fallback,
                                {"known_hours": row.known_hours, "estimated_elapsed": row.imputed_elapsed,
                                 "overnight_carry": row.carry, "suspect_overlap": bool(row.overlapping_records),
                                 "unknown_records": row.unknown_records, "missing_clockouts": row.missing_clockouts,
                                 "future_end_masked": row.future_end_masked, "no_records": row.no_records,
                                 "usual_hours": usual, "usual_band": band, "wednesday_days": row.days,
                                 "cell_weeks": len(cell), "cell_breaches": sum(bool(p.outcome.target_will_breach) for p in cell),
                                 "peer_breach_rate": broader, "table_prior_rows": TABLE_PRIOR_ROWS}))
    return tuple(results)
