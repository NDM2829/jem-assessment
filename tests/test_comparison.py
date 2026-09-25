"""The selected deployment must follow the declared common replay, without leakage."""

from dataclasses import replace
from pathlib import Path

from jem.comparison import METHODS, STATISTICAL, evaluate, select_statistical_candidate
from jem.features import build_history, source_shifts
from jem.io import demo_sources
from jem.pipeline import ingest
from jem.predictors.matched_historical_remaining_hours import predict as matched_predict
from jem.predictors.reference_stats import prior_usual_hours
from jem.predictors.smoothed_risk_table import predict as table_predict
from jem.workflow import load_policy, process_bundle

ROOT = Path(__file__).parents[1]


def _inputs():
    ingested = ingest(demo_sources(ROOT))
    history = build_history(source_shifts(ingested), ingested.employees_by_id, ingested.reporting.week_start)
    policy = load_policy(ROOT / "config" / "prediction_policy.toml")
    return ingested, history, policy


def test_selection_tie_break_order():
    rows = {name: {"F2": 0.4, "recall": 0.6, "FP": 20, "all_review_alerts": 30}
            for name in STATISTICAL}
    assert select_statistical_candidate(rows) == "correlated_hours"  # Method name last.
    rows["matched_historical_remaining_hours"]["all_review_alerts"] = 29
    assert select_statistical_candidate(rows) == "matched_historical_remaining_hours"
    rows["smoothed_risk_table"]["FP"] = 19
    assert select_statistical_candidate(rows) == "smoothed_risk_table"
    rows["correlated_hours"]["recall"] = 0.61
    assert select_statistical_candidate(rows) == "correlated_hours"
    rows["matched_historical_remaining_hours"]["F2"] = 0.41
    assert select_statistical_candidate(rows) == "matched_historical_remaining_hours"


def test_four_method_replay_and_predeclared_selection():
    ingested, history, policy = _inputs()
    report = evaluate(history, policy.config, ingested.reporting.week_start)
    assert set(report["summary"]) == set(METHODS)
    assert set(report["probability"]) == set(STATISTICAL)
    assert len(report["weeks"]["all_completed"]) == 9
    assert len(report["weeks"]["threshold_seeds"]) == 2
    assert len(report["weeks"]["main"]) == 6
    assert {m: (r["TP"], r["FP"], r["FN"]) for m, r in report["summary"].items()} == {
        "correlated_hours": (24, 137, 20),
        "smoothed_risk_table": (31, 283, 13),
        "matched_historical_remaining_hours": (23, 177, 21),
        "naive": (23, 260, 21),
    }
    for method, row in report["summary"].items():
        assert (row["rows"], row["eligible"], row["excluded"], row["breaches"]) == (1278, 1107, 171, 44)
        assert row["all_review_alerts"] == row["TP"] + row["FP"] + row["unknown_outcome_alerts"]
        assert sum(w["TP"] for w in report["weekly"][method]) == row["TP"]
        assert len(report["equal_review_budget"][method]) == 4
    assert report["summary"]["correlated_hours"]["F2"] > report["summary"]["smoothed_risk_table"]["F2"]
    assert report["summary"]["smoothed_risk_table"]["F2"] > report["summary"]["matched_historical_remaining_hours"]["F2"]
    assert report["summary"]["matched_historical_remaining_hours"]["F2"] > report["summary"]["naive"]["F2"]
    assert report["selected"]["method"] == policy.selected_method == "correlated_hours"
    assert report["selected"]["deployment_threshold"] == policy.config.threshold == 0.05
    assert report["selected"]["threshold_source_eligible_rows"] == 1475
    assert report["selected"]["threshold_set_for_week"] == ingested.reporting.week_start.isoformat()
    assert report["selected"]["F2_difference_vs_naive"] > 0
    assert len(report["weekly_thresholds"]["correlated_hours"]) == 6
    for method in STATISTICAL:
        assert all(row["last_training_week"] < row["week"] for row in report["weekly_thresholds"][method])
        assert report["probability"][method]["Brier"] >= 0
        assert sum(band["n"] for band in report["probability"][method]["calibration"]) == 1107
    assert "naive" not in report["probability"]  # Its score is projected hours, not probability.
    assert len({row["reviews_per_week"] for row in report["equal_review_budget"]["naive"]}) == 4


def test_reference_states_and_forecasts_do_not_look_ahead():
    ingested, history, policy = _inputs()
    weeks = sorted({row.snapshot.week_start for row in history})
    probe = weeks[3]
    previous = tuple(row for row in history if row.snapshot.week_start < probe)
    current = tuple(row.snapshot for row in history if row.snapshot.week_start == probe)
    states = prior_usual_hours(history, probe, policy.config)
    first_week = weeks[0]
    assert all(value is None for (employee_id, week), value in states.items() if week == first_week)
    assert any(value is not None for (employee_id, week), value in states.items() if week == weeks[1])
    # A donor's past-only usual-hours state stays the same when later outcomes change.
    changed = tuple(replace(row, total_hours=999, R=999, outcome=replace(row.outcome,
                    target_will_breach=False)) if row.snapshot.week_start >= probe else row for row in history)
    assert prior_usual_hours(changed, probe, policy.config) == states
    for predict in (table_predict, matched_predict):
        baseline = predict(current, previous, policy.config)
        altered = predict(current, changed, policy.config)
        assert [(row.employee_id, row.risk_score) for row in altered] == [
            (row.employee_id, row.risk_score) for row in baseline]
        assert all(row.explanation_facts["known_hours"] >= 0 for row in baseline)


def test_app_and_selected_export_agree_with_root_artifacts():
    ingested, _, policy = _inputs()
    processed = process_bundle(ingested, policy)
    assert processed.predictions_csv == (ROOT / "predictions.csv").read_bytes()
    assert processed.note_classifications_csv == (ROOT / "note_classifications.csv").read_bytes()
    assert {row.forecast.method_version for row in processed.queue} == {policy.config.method_version}
    assert all(row.forecast.threshold == policy.config.threshold for row in processed.queue)
