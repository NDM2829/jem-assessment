"""Past-only clean reference groups shared by the two Step 8 methods."""

from __future__ import annotations

from statistics import mean

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import PredictorConfig, ProcessingError


def clean_before(history: tuple[HistoricalRow, ...], week) -> tuple[HistoricalRow, ...]:
    return tuple(row for row in history if row.snapshot.week_start < week and row.outcome.label_eligible)


def groups(row: Snapshot, reference: tuple[HistoricalRow, ...], config: PredictorConfig,
           *, allow_global_fallback: bool = False
           ) -> tuple[tuple[HistoricalRow, ...], tuple[HistoricalRow, ...], str | None]:
    own = tuple(past for past in reference if past.snapshot.employee_id == row.employee_id)
    peer = tuple(past for past in reference if past.snapshot.employee_id != row.employee_id
                 and past.snapshot.role == row.role and past.snapshot.shift_pattern == row.shift_pattern)
    fallback = None
    if len(peer) < config.peer_minimum_weeks:
        peer = tuple(past for past in reference if past.snapshot.employee_id != row.employee_id)
        fallback = "all_other_employees"
    if not own:
        fallback = "peer_only" if fallback is None else "peer_only;all_other_employees"
    if not peer and allow_global_fallback:
        fallback = "global_reference_prevalence"
    elif not peer:
        raise ProcessingError("No clean earlier peer employee-weeks support prediction; upload more completed history.")
    return own, peer, fallback


def usual_hours(row: Snapshot, reference: tuple[HistoricalRow, ...], config: PredictorConfig) -> float:
    own, peer, _ = groups(row, reference, config, allow_global_fallback=True)
    peer_mean = mean(past.total_hours for past in peer or reference)
    if not own:
        return peer_mean
    weight = len(own) / (len(own) + config.personal_prior_weeks)
    return weight * mean(past.total_hours for past in own) + (1 - weight) * peer_mean


def prior_usual_hours(history: tuple[HistoricalRow, ...], week, config: PredictorConfig
                      ) -> dict[tuple[str, object], float | None]:
    """A donor's state is built from weeks before that donor, never from hindsight."""
    earlier = clean_before(history, week)
    by_week = sorted({row.snapshot.week_start for row in earlier})
    states = {}
    for donor_week in by_week:
        prior = tuple(row for row in earlier if row.snapshot.week_start < donor_week)
        for row in earlier:
            if row.snapshot.week_start == donor_week:
                states[(row.snapshot.employee_id, donor_week)] = (
                    usual_hours(row.snapshot, prior, config) if prior else None)
    return states
