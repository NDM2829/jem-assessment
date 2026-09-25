"""Common, chronological Step 8 comparison over shared production forecasts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from statistics import mean

from jem.evaluation import ReplayRow, choose_threshold
from jem.features import HistoricalRow
from jem.predictors.base import PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict as correlated_predict
from jem.predictors.matched_historical_remaining_hours import predict as matched_predict
from jem.predictors.naive import predict as naive_predict
from jem.predictors.smoothed_risk_table import predict as table_predict

METHODS = ("naive", "correlated_hours", "smoothed_risk_table", "matched_historical_remaining_hours")
STATISTICAL = METHODS[1:]
PREDICTORS = {"naive": naive_predict, "correlated_hours": correlated_predict,
              "smoothed_risk_table": table_predict, "matched_historical_remaining_hours": matched_predict}
VERSIONS = {"correlated_hours": "correlated-hours-1.0", "smoothed_risk_table": "smoothed-risk-table-1.0",
            "matched_historical_remaining_hours": "matched-remainder-1.0"}
CALIBRATION_BANDS = ((0.0, 0.025), (0.025, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 1.0))
BUDGETS = (10, 20, 30, 40)


@dataclass(frozen=True)
class ScoreRow:
    week: date
    employee_id: str
    method: str
    score: float  # Naive is projected HOURS; all other methods are probabilities.
    eligible: bool
    target: bool | None


def _metrics(rows: tuple[tuple[ScoreRow, bool], ...]) -> dict:
    eligible = [(row, alert) for row, alert in rows if row.eligible]
    tp = sum(bool(alert and row.target) for row, alert in eligible)
    fp = sum(bool(alert and not row.target) for row, alert in eligible)
    fn = sum(bool(not alert and row.target) for row, alert in eligible)
    total_alerts = sum(bool(alert) for _, alert in rows)
    return {"rows": len(rows), "eligible": len(eligible), "excluded": len(rows) - len(eligible),
            "breaches": tp + fn, "TP": tp, "FP": fp, "FN": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "F2": 5 * tp / (5 * tp + 4 * fn + fp) if 5 * tp + 4 * fn + fp else 0.0,
            "all_review_alerts": total_alerts,
            "unknown_outcome_alerts": sum(bool(alert) for row, alert in rows if not row.eligible)}


def _calibration(rows: tuple[ScoreRow, ...]) -> list[dict]:
    eligible = [row for row in rows if row.eligible]
    bands = []
    for index, (low, high) in enumerate(CALIBRATION_BANDS):
        group = [row for row in eligible if (low <= row.score <= high if index == 0 else low < row.score <= high)]
        bands.append({"band": f"[{low:.3f}, {high:.3f}]" if index == 0 else f"({low:.3f}, {high:.3f}]",
                      "n": len(group), "breaches": sum(bool(row.target) for row in group),
                      "mean_risk": mean(row.score for row in group) if group else None,
                      "observed_rate": mean(bool(row.target) for row in group) if group else None})
    if sum(band["n"] for band in bands) != len(eligible):
        raise ValueError("Calibration bands did not cover every eligible probability.")
    return bands


def _budget(rows: tuple[ScoreRow, ...], main_weeks: tuple[date, ...]) -> list[dict]:
    results = []
    total_breaches = sum(bool(row.target) for row in rows if row.eligible)
    for budget in BUDGETS:
        selected = []
        for week in main_weeks:
            current = [row for row in rows if row.week == week]
            selected.extend(sorted(current, key=lambda row: (-row.score, row.employee_id))[:budget])
        tp = sum(bool(row.target) for row in selected if row.eligible)
        fp = sum(not row.target for row in selected if row.eligible)
        results.append({"reviews_per_week": budget, "TP": tp, "FP": fp, "FN": total_breaches - tp,
                        "recall": tp / total_breaches if total_breaches else 0.0,
                        "unknown_outcome_alerts": sum(not row.eligible for row in selected),
                        "all_review_alerts": len(selected)})
    return results


def select_statistical_candidate(summaries: dict[str, dict],
                                 candidates: tuple[str, ...] = STATISTICAL) -> str:
    """The predeclared Step 1 lexicographic ranking, with no fitted parameters."""
    return sorted(candidates, key=lambda method: (-summaries[method]["F2"],
                  -summaries[method]["recall"], summaries[method]["FP"],
                  summaries[method]["all_review_alerts"], method))[0]


def evaluate(history: tuple[HistoricalRow, ...], config: PredictorConfig,
             current_week: date) -> dict:
    """W1 reference; W2/W3 seeds; W4 onward replay, all positions from the data."""
    weeks = tuple(sorted({row.snapshot.week_start for row in history}))
    if len(weeks) < 4 or weeks[-1] >= current_week:
        raise ProcessingError("Need W1 and at least three completed weeks before the current reporting week.")
    register = {row.snapshot.employee_id for row in history if row.snapshot.week_start == weeks[0]}
    if any({row.snapshot.employee_id for row in history if row.snapshot.week_start == week} != register for week in weeks):
        raise ValueError("Historical snapshots must cover the same employee register each week.")
    main_weeks = weeks[3:]
    excluded_reasons = Counter(reason for row in history if row.snapshot.week_start in main_weeks
                               and not row.outcome.label_eligible for reason in row.outcome.exclusion_reasons)
    predictions: dict[str, list[ScoreRow]] = {method: [] for method in METHODS}
    decisions: dict[str, list[tuple[ScoreRow, bool]]] = {method: [] for method in METHODS}
    weekly: dict[str, list[dict]] = {method: [] for method in METHODS}
    thresholds: dict[str, list[dict]] = {method: [] for method in STATISTICAL}
    for position, week in enumerate(weeks[1:], start=1):
        current = tuple(row for row in history if row.snapshot.week_start == week)
        previous = tuple(row for row in history if row.snapshot.week_start < week)
        outcomes = {row.snapshot.employee_id: row.outcome for row in current}
        snapshots = tuple(row.snapshot for row in current)
        for method in METHODS:
            method_config = replace(config, method_version=VERSIONS.get(method, "naive-hours-1.0"))
            forecasts = PREDICTORS[method](snapshots, previous, method_config)
            if {row.employee_id for row in forecasts} != register or len(forecasts) != len(register):
                raise ValueError("Every historical method must score each registered employee once per week.")
            now = tuple(ScoreRow(week, forecast.employee_id, method,
                                 forecast.explanation_facts["projection_hours"] if method == "naive" else forecast.risk_score,
                                 outcomes[forecast.employee_id].label_eligible,
                                 outcomes[forecast.employee_id].target_will_breach)
                        for forecast in forecasts)
            if method != "naive" and any(not 0 <= row.score <= 1 for row in now):
                raise ValueError("Statistical scores must be probabilities in [0, 1].")
            if position >= 3:
                if method == "naive":
                    threshold = 55.0
                    selected = tuple((row, row.score > threshold) for row in now)
                else:
                    prior = tuple(predictions[method])
                    threshold = choose_threshold(tuple(ReplayRow(row.week, row.employee_id, row.score,
                                                                 row.eligible, row.target) for row in prior))
                    thresholds[method].append({"week": week.isoformat(), "threshold": threshold,
                                               "last_training_week": max(row.week for row in prior).isoformat(),
                                               "earlier_eligible_rows": sum(row.eligible for row in prior)})
                    selected = tuple((row, row.score >= threshold) for row in now)
                decisions[method].extend(selected)
                weekly[method].append({"week": week.isoformat(), "threshold": threshold, **_metrics(selected)})
            predictions[method].extend(now)
    summaries = {method: _metrics(tuple(decisions[method])) for method in METHODS}
    chosen = select_statistical_candidate(summaries)
    selected_history = tuple(predictions[chosen])
    deployment_threshold = choose_threshold(tuple(ReplayRow(row.week, row.employee_id, row.score,
                                                            row.eligible, row.target) for row in selected_history))
    probability = {}
    for method in STATISTICAL:
        main = tuple(row for row in predictions[method] if row.week in main_weeks and row.eligible)
        probability[method] = {"Brier": mean((row.score - int(row.target)) ** 2 for row in main),
                               "mean_risk": mean(row.score for row in main),
                               "observed_rate": mean(bool(row.target) for row in main),
                               "calibration": _calibration(main)}
    budgets = {method: _budget(tuple(row for row in predictions[method] if row.week in main_weeks), main_weeks)
               for method in METHODS}
    baseline = summaries["naive"]
    winner = summaries[chosen]
    return {"policy": {"statistical_candidates": list(STATISTICAL), "baseline": "naive",
                       "selection": "highest pooled chronological F2; higher recall; fewer FP; fewer all alerts; method name",
                       "weekly_threshold": "earlier eligible out-of-time scores; 0.00..1.00 by 0.01; highest F2; fewer FP; higher threshold",
                       "naive_rule": "Wednesday A * 7/3 strictly > 55 hours"},
            "weeks": {"all_completed": [week.isoformat() for week in weeks],
                      "reference_only": weeks[0].isoformat(), "threshold_seeds": [week.isoformat() for week in weeks[1:3]],
                      "main": [week.isoformat() for week in main_weeks], "current": current_week.isoformat()},
            "summary": summaries, "weekly": weekly, "weekly_thresholds": thresholds,
            "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
            "probability": probability, "equal_review_budget": budgets,
            "selected": {"method": chosen, "main_F2": winner["F2"], "naive_F2": baseline["F2"],
                         "F2_difference_vs_naive": winner["F2"] - baseline["F2"],
                         "TP_difference_vs_naive": winner["TP"] - baseline["TP"],
                         "FP_difference_vs_naive": winner["FP"] - baseline["FP"],
                         "all_review_alerts_difference_vs_naive": winner["all_review_alerts"] - baseline["all_review_alerts"],
                         "deployment_threshold": deployment_threshold,
                         "threshold_source_weeks": [week.isoformat() for week in weeks[1:]],
                         "threshold_source_eligible_rows": sum(row.eligible for row in selected_history),
                         "threshold_set_for_week": current_week.isoformat()},
            "limitations": ["All historical weeks supplied here already informed method design; this shared-code replay is not independent validation.",
                            "Confusion metrics use only clean labelled employee-weeks; excluded rows still count in review workload.",
                            "Scores are not proven calibrated; missing clock-outs and overlaps retain the initial reference quality policy."]}
