"""Validated submission CSV and non-sensitive run metadata."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Mapping

from jem.predictors.base import Forecast


PREDICTION_COLUMNS = ("employee_id", "will_breach", "risk_score")


def validate_forecasts(forecasts: tuple[Forecast, ...], employee_ids: set[str]) -> None:
    ids = [row.employee_id for row in forecasts]
    if len(ids) != len(employee_ids) or set(ids) != employee_ids or len(ids) != len(set(ids)):
        raise ValueError("Prediction export must cover every registered employee exactly once.")
    if not forecasts:
        raise ValueError("Prediction export has no employees.")
    for row in forecasts:
        if type(row.will_breach) is not bool or row.risk_score is None or not math.isfinite(row.risk_score) or not 0 <= row.risk_score <= 1:
            raise ValueError("Every final prediction needs a binary decision and finite risk in [0, 1].")
    if len({row.week_start for row in forecasts}) != 1:
        raise ValueError("Prediction export contains multiple reporting weeks.")


def predictions_csv_bytes(forecasts: tuple[Forecast, ...], employee_ids: set[str]) -> bytes:
    """Single validated serializer for CLI files and browser downloads."""
    validate_forecasts(forecasts, employee_ids)
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=PREDICTION_COLUMNS)
    writer.writeheader()
    for row in sorted(forecasts, key=lambda r: r.employee_id):
        writer.writerow({"employee_id": row.employee_id, "will_breach": int(row.will_breach),
                         "risk_score": format(row.risk_score, ".12g")})
    return handle.getvalue().encode("utf-8")


def write_predictions(path: str | Path, forecasts: tuple[Forecast, ...], employee_ids: set[str]) -> None:
    Path(path).write_bytes(predictions_csv_bytes(forecasts, employee_ids))


def source_hashes(sources: Mapping[str, Path]) -> dict[str, str]:
    """Hash input bytes without including sensitive source values in metadata."""
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in sorted(sources.items())}


def write_manifest(path: str | Path, *, forecasts: tuple[Forecast, ...], input_hashes: dict[str, str],
                   policy_version: str, threshold_rule: str, threshold_source_weeks: str,
                   threshold_source_eligible_rows: int, reporting_mode: str) -> None:
    if not forecasts:
        raise ValueError("Cannot write a manifest without forecasts.")
    first = forecasts[0]
    document = {
        "reporting_week_start": first.week_start.isoformat(),
        "reporting_week_end": first.week_end.isoformat(),
        "reporting_mode": reporting_mode,
        "forecast_cutoff": "Thursday 00:00 Africa/Johannesburg",
        "method_version": first.method_version,
        "policy_version": policy_version,
        "threshold": first.threshold,
        "threshold_rule": threshold_rule,
        "threshold_source_weeks": threshold_source_weeks,
        "threshold_source_eligible_rows": threshold_source_eligible_rows,
        "employee_count": len(forecasts),
        "overlap_flagged_employees": sum(bool(row.explanation_facts.get("suspect_overlap")) for row in forecasts),
        "unavailable_clockout_records": sum(int(row.explanation_facts.get("missing_clockouts", 0)) for row in forecasts),
        "future_clockouts_masked": sum(int(row.explanation_facts.get("future_end_masked", 0)) for row in forecasts),
        "input_sha256": input_hashes,
        "limitations": "Overlap-affected sums are suspect, not confirmed worked hours or confirmed breaches. Note classifications are a separate output; independent human note validation and the statistical-model comparison remain pending.",
    }
    Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
