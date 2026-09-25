"""Export real current-week predictions with the versioned frozen threshold."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import tomli

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.exports import source_hashes, write_manifest, write_predictions
from jem.features import build_history, build_snapshot, source_shifts
from jem.io import demo_sources
from jem.pipeline import ingest
from jem.predictors.base import PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Stage 3 breach predictions")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--as-of", default=None, help="Selected reporting date, YYYY-MM-DD")
    args = parser.parse_args()
    sources = demo_sources(ROOT) if args.data_dir == ROOT / "data" / "demo" else {
        name: path for name in ("employees.csv", "shifts.csv", "sites.csv", "shift_notes.csv",
                               "public_holidays.csv", "weekly_summary.csv", "payroll_details.csv")
        if (path := args.data_dir / name).is_file()
    }
    result = ingest(sources, as_of=args.as_of)
    if not result.accepted:
        raise ProcessingError("Input bundle rejected; inspect structured ingestion issues before exporting.")
    if result.reporting.mode == "before_wednesday":
        raise ProcessingError("Export ends before Wednesday; supply records through Wednesday for this forecast.")
    with (ROOT / "config" / "prediction_policy.toml").open("rb") as handle:
        policy = tomli.load(handle)
    deployment = policy["deployment"]
    config = PredictorConfig(policy["policy_version"], deployment["method_version"], deployment["threshold"],
                             deployment["personal_prior_weeks"], deployment["peer_minimum_weeks"],
                             deployment["variance_floor"], deployment["correlation_cap"])
    shifts = source_shifts(result)
    week = result.reporting.week_start
    history = build_history(shifts, result.employees_by_id, week)
    snapshot = build_snapshot(shifts, result.employees_by_id, week)
    forecasts = predict(snapshot, history, config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_predictions(args.output_dir / "predictions.csv", forecasts, set(result.employees_by_id))
    write_manifest(args.output_dir / "predictions_manifest.json", forecasts=forecasts,
                   input_hashes=source_hashes(sources), policy_version=config.policy_version,
                   threshold_rule=deployment["threshold_rule"],
                   threshold_source_weeks=deployment["threshold_source_weeks"],
                   threshold_source_eligible_rows=deployment["threshold_source_eligible_rows"],
                   reporting_mode=result.reporting.mode)
    print(f"Exported {len(forecasts)} predictions for {week} ({result.reporting.mode}).")


if __name__ == "__main__":
    try:
        main()
    except ProcessingError as exc:
        raise SystemExit(f"Cannot process export: {exc}") from None
