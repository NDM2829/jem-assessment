import csv
from datetime import date

import pytest

from jem.exports import write_predictions
from jem.predictors.base import Forecast


def forecast(employee_id, score):
    return Forecast(employee_id, score >= 0.05, score, date(2026, 8, 10), date(2026, 8, 16),
                    0.05, "correlated-hours-1.0", "peer_weeks=10", None, {})


def test_export_has_exact_columns_and_complete_register(tmp_path):
    path = tmp_path / "predictions.csv"
    write_predictions(path, (forecast("002", 0.2), forecast("001", 0.01)), {"001", "002"})
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["employee_id", "will_breach", "risk_score"]
        assert list(reader) == [
            {"employee_id": "001", "will_breach": "0", "risk_score": "0.01"},
            {"employee_id": "002", "will_breach": "1", "risk_score": "0.2"},
        ]


@pytest.mark.parametrize("rows,register", [
    ((forecast("001", 0.2),), {"001", "002"}),
    ((forecast("001", 0.2), forecast("001", 0.3)), {"001"}),
    ((forecast("001", float("nan")),), {"001"}),
    ((forecast("001", 1.01),), {"001"}),
])
def test_export_rejects_missing_duplicate_or_invalid_scores(tmp_path, rows, register):
    with pytest.raises(ValueError):
        write_predictions(tmp_path / "predictions.csv", rows, register)
