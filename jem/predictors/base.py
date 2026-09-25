"""Shared prediction contract and fixed versioned policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math


class ProcessingError(ValueError):
    """Actionable data/history failure; callers must not invent a score."""


@dataclass(frozen=True)
class PredictorConfig:
    policy_version: str
    method_version: str
    threshold: float
    personal_prior_weeks: float = 4.0
    peer_minimum_weeks: int = 10
    variance_floor: float = 1.0
    correlation_cap: float = 0.95

    def __post_init__(self) -> None:
        if not (math.isfinite(self.threshold) and 0 <= self.threshold <= 1):
            raise ValueError("A fixed numeric threshold in [0, 1] is required.")


@dataclass(frozen=True)
class Forecast:
    employee_id: str
    will_breach: bool
    risk_score: float | None
    week_start: date
    week_end: date
    threshold: float
    method_version: str
    support: str
    fallback: str | None
    explanation_facts: dict[str, float | int | bool | str | None]


def forecast_period(week_start: date) -> date:
    return week_start + timedelta(days=6)
