"""Reference correlated Wednesday/remaining-hours tail probability."""

from __future__ import annotations

import math
from statistics import mean

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import Forecast, PredictorConfig, ProcessingError, forecast_period


def _moments(rows: list[HistoricalRow]) -> tuple[tuple[float, float], tuple[float, float, float]]:
    if len(rows) < 2:
        raise ProcessingError("At least two clean earlier reference weeks are needed to estimate peer covariance.")
    ma = mean(r.A for r in rows)
    mr = mean(r.R for r in rows)
    denominator = len(rows) - 1
    va = sum((r.A - ma) ** 2 for r in rows) / denominator
    vr = sum((r.R - mr) ** 2 for r in rows) / denominator
    cov = sum((r.A - ma) * (r.R - mr) for r in rows) / denominator
    return (ma, mr), (va, vr, cov)


def _sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def _truncated_tail(gap: float, conditional_mean: float, sd: float) -> float:
    if gap < 0:
        return 1.0
    numerator = _sf((gap - conditional_mean) / sd)
    denominator = _sf(-conditional_mean / sd)
    if denominator == 0:
        raise ProcessingError("Reference tail calculation underflowed; inspect the historical distribution.")
    return min(1.0, max(0.0, numerator / denominator))


def predict(snapshot: tuple[Snapshot, ...], history: tuple[HistoricalRow, ...], config: PredictorConfig) -> tuple[Forecast, ...]:
    if not snapshot:
        return ()
    week = snapshot[0].week_start
    if any(row.week_start != week for row in snapshot):
        raise ValueError("Predict one reporting week at a time.")
    ref = [row for row in history if row.snapshot.week_start < week and row.outcome.label_eligible]
    if not ref:
        raise ProcessingError("No clean earlier historical weeks support correlated-hours prediction; upload earlier complete shifts.")
    result = []
    for row in snapshot:
        own = [past for past in ref if past.snapshot.employee_id == row.employee_id]
        peers = [past for past in ref if past.snapshot.employee_id != row.employee_id
                 and past.snapshot.role == row.role and past.snapshot.shift_pattern == row.shift_pattern]
        fallback = None
        if len(peers) < config.peer_minimum_weeks:
            peers = [past for past in ref if past.snapshot.employee_id != row.employee_id]
            fallback = "all_other_employees"
        if not own:
            fallback = "peer_only" if fallback is None else "peer_only;all_other_employees"
        if len(peers) < 2:
            raise ProcessingError("Too few clean peer employee-weeks for covariance; upload more completed history.")
        (ma, mr), (va, vr, cov) = _moments(peers)
        if own:
            own_ma, own_mr = mean(p.A for p in own), mean(p.R for p in own)
            weight = len(own) / (len(own) + config.personal_prior_weeks)
            own_va, own_vr, own_cov = _moments(own)[1] if len(own) >= 2 else (va, vr, cov)
            delta_a, delta_r = own_ma - ma, own_mr - mr
            va = weight * own_va + (1 - weight) * va + weight * (1 - weight) * delta_a ** 2
            vr = weight * own_vr + (1 - weight) * vr + weight * (1 - weight) * delta_r ** 2
            cov = weight * own_cov + (1 - weight) * cov + weight * (1 - weight) * delta_a * delta_r
            ma = weight * own_ma + (1 - weight) * ma
            mr = weight * own_mr + (1 - weight) * mr
        va = max(va, config.variance_floor)
        vr = max(vr, config.variance_floor)
        rho = min(config.correlation_cap, max(-config.correlation_cap, cov / math.sqrt(va * vr)))
        conditional_mean = mr + rho * math.sqrt(vr / va) * (row.A - ma)
        sd = math.sqrt(vr * (1 - rho * rho) * (1 + 1 / (len(own) + config.personal_prior_weeks)))
        risk = _truncated_tail(55 - row.A, conditional_mean, sd)
        # Reference certainty override applies only to completed observed hours.
        if row.known_hours > 55:
            risk = 1.0
        result.append(Forecast(row.employee_id, risk >= config.threshold, risk, week, forecast_period(week),
                               config.threshold, config.method_version, f"personal_weeks={len(own)};peer_weeks={len(peers)}",
                               fallback,
                               {"known_hours": row.known_hours, "estimated_elapsed": row.imputed_elapsed,
                                "overnight_carry": row.carry, "suspect_overlap": bool(row.overlapping_records),
                                "unknown_records": row.unknown_records, "missing_clockouts": row.missing_clockouts,
                                "future_end_masked": row.future_end_masked, "no_records": row.no_records,
                                "conditional_remaining_mean": conditional_mean,
                                "conditional_remaining_sd": sd, "conditional_correlation": rho}))
    return tuple(result)
