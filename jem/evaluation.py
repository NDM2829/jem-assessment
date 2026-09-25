"""Offline chronological replay for the initial correlated-hours threshold."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict as correlated_predict
from jem.predictors.naive import predict as naive_predict


@dataclass(frozen=True)
class ReplayRow:
    week_start: date
    employee_id: str
    score: float
    eligible: bool
    target: bool | None


@dataclass(frozen=True)
class ReplayWeek:
    week_start: date
    threshold: float
    correlated_tp: int
    correlated_fp: int
    correlated_fn: int
    naive_tp: int
    naive_fp: int
    naive_fn: int


def choose_threshold(rows: tuple[ReplayRow, ...]) -> float:
    labelled = [r for r in rows if r.eligible and r.target is not None]
    if not labelled:
        raise ProcessingError("No earlier eligible out-of-time forecasts support threshold selection.")
    choices = []
    for step in range(101):
        threshold = step / 100
        tp = sum(r.score >= threshold and r.target for r in labelled)
        fp = sum(r.score >= threshold and not r.target for r in labelled)
        fn = sum(r.score < threshold and r.target for r in labelled)
        f2 = 5 * tp / max(5 * tp + 4 * fn + fp, 1)
        choices.append((f2, -fp, threshold))
    return max(choices)[2]


def _counts(rows: tuple[ReplayRow, ...], threshold: float, *, strict: bool = False) -> tuple[int, int, int]:
    eligible = [r for r in rows if r.eligible and r.target is not None]
    tp = sum((r.score > threshold if strict else r.score >= threshold) and r.target for r in eligible)
    fp = sum((r.score > threshold if strict else r.score >= threshold) and not r.target for r in eligible)
    fn = sum((r.score <= threshold if strict else r.score < threshold) and r.target for r in eligible)
    return tp, fp, fn


def replay(history: tuple[HistoricalRow, ...], config: PredictorConfig) -> tuple[tuple[ReplayWeek, ...], tuple[ReplayRow, ...], tuple[ReplayRow, ...]]:
    weeks = sorted({r.snapshot.week_start for r in history})
    if len(weeks) < 4:
        raise ProcessingError("Need W1 reference and W2/W3 threshold-seeding weeks before replay.")
    correlated: list[ReplayRow] = []
    naive: list[ReplayRow] = []
    results = []
    for position, week in enumerate(weeks):
        if position == 0:
            continue
        current = [r for r in history if r.snapshot.week_start == week]
        snaps = tuple(r.snapshot for r in current)
        labels = {r.snapshot.employee_id: r.outcome for r in current}
        c = correlated_predict(snaps, history, config)
        n = naive_predict(snaps, history, config)
        now_c = tuple(ReplayRow(week, r.employee_id, r.risk_score, labels[r.employee_id].label_eligible,
                                labels[r.employee_id].target_will_breach) for r in c)
        now_n = tuple(ReplayRow(week, r.employee_id, r.explanation_facts["projection_hours"],
                                labels[r.employee_id].label_eligible, labels[r.employee_id].target_will_breach) for r in n)
        if position >= 3:
            threshold = choose_threshold(tuple(correlated))
            results.append(ReplayWeek(week, threshold, *_counts(now_c, threshold), *_counts(now_n, 55, strict=True)))
        correlated.extend(now_c)
        naive.extend(now_n)
    return tuple(results), tuple(correlated), tuple(naive)
