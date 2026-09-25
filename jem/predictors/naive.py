"""Reference naive Wednesday projection comparator, in hours rather than risk."""

from __future__ import annotations

from jem.features import HistoricalRow, Snapshot
from jem.predictors.base import Forecast, PredictorConfig, forecast_period


def predict(snapshot: tuple[Snapshot, ...], history: tuple[HistoricalRow, ...], config: PredictorConfig) -> tuple[Forecast, ...]:
    del history
    return tuple(Forecast(row.employee_id, row.A * 7 / 3 > 55, None, row.week_start,
                          forecast_period(row.week_start), 55.0, "naive-hours-1.0", "Wednesday projection ×7/3",
                          None, {"projection_hours": row.A * 7 / 3, "known_hours": row.known_hours,
                                 "estimated_elapsed": row.imputed_elapsed, "suspect_overlap": bool(row.overlapping_records)})
                 for row in snapshot)
