from datetime import date, datetime
import math

from jem.evaluation import choose_threshold, replay
from jem.features import Snapshot, build_history, build_outcomes, build_snapshot, reconcile_weekly_summary, source_shifts
from jem.hours import find_overlaps, mask_after_cutoff, parse_shift
from jem.pipeline import ingest_demo
from jem.pipeline import ingest
from jem.predictors.base import PredictorConfig, ProcessingError
from jem.predictors.correlated_hours import predict as correlated_predict
from jem.predictors.naive import predict as naive_predict
import pytest


def shift(identifier, employee, site, day, start, end):
    return parse_shift({"shift_id": identifier, "employee_id": employee, "site_id": site,
                        "shift_date": day, "clock_in_time": start, "clock_out_time": end})


def test_equal_clock_and_overnight_week_boundary():
    ambiguous = shift("same", "E", "S", "2026-08-09", "08:00", "08:00")
    sunday = shift("sun", "E", "S1", "2026-08-09", "22:00", "02:00")
    monday = shift("mon", "E", "S2", "2026-08-10", "01:00", "03:00")
    assert ambiguous.invalid_time and ambiguous.recorded_hours is None
    assert sunday.recorded_hours == 4 and sunday.week_start == date(2026, 8, 3)
    assert len(find_overlaps((sunday, monday))) == 1
    snaps = build_snapshot((sunday, monday), {"E": {"role": "R", "shift_pattern": "P"}}, date(2026, 8, 10))
    assert snaps[0].known_hours == 2
    assert snaps[0].overlap_shift_ids == ("mon",)


def test_touching_intervals_do_not_overlap():
    first = shift("1", "E", "A", "2026-08-10", "08:00", "12:00")
    second = shift("2", "E", "B", "2026-08-10", "12:00", "16:00")
    assert find_overlaps((first, second)) == ()


def test_future_clockout_masked_before_estimation_and_carry():
    prior = shift("old", "E", "S", "2026-08-03", "08:00", "16:00")
    future = shift("new", "E", "S", "2026-08-12", "22:00", "06:00")
    cutoff = datetime(2026, 8, 13)
    assert mask_after_cutoff(future, cutoff).recorded_hours is None
    snap = build_snapshot((prior, future), {"E": {"role": "R", "shift_pattern": "P"}}, date(2026, 8, 10))[0]
    assert (snap.known_hours, snap.imputed_elapsed, snap.carry) == (0, 2, 6)
    assert snap.future_end_masked == 1 and snap.missing_clockouts == 0
    changed_future = shift("new", "E", "S", "2026-08-12", "22:00", "07:00")
    replacement = build_snapshot((prior, changed_future), {"E": {"role": "R", "shift_pattern": "P"}}, date(2026, 8, 10))[0]
    assert (replacement.known_hours, replacement.imputed_elapsed, replacement.carry) == (snap.known_hours, snap.imputed_elapsed, snap.carry)


def test_outcome_strictly_greater_than_55_and_no_current_records():
    durations = [8, 8, 8, 8, 8, 8, 7]
    rows = tuple(shift(str(i), "E", "S", str(date(2026, 8, 3 + i)), "08:00", f"{8 + hours:02d}:00")
                 for i, hours in enumerate(durations))
    register = {"E": {"role": "R", "shift_pattern": "P"}, "N": {"role": "R", "shift_pattern": "P"}}
    outcomes = build_outcomes(rows, register, date(2026, 8, 10))
    e = next(o for o in outcomes if o.employee_id == "E")
    n = next(o for o in outcomes if o.employee_id == "N")
    assert e.recorded_hours == 55 and e.target_will_breach is False
    assert n.target_will_breach is None and "no_shift_records" in n.exclusion_reasons
    changed = rows[:-1] + (shift("6", "E", "S", "2026-08-09", "08:00", "15:15"),)
    assert next(o for o in build_outcomes(changed, register, date(2026, 8, 10)) if o.employee_id == "E").target_will_breach is True
    snaps = build_snapshot(rows, register, date(2026, 8, 10))
    assert len(snaps) == 2 and all(s.no_records for s in snaps)


def test_naive_projection_is_hours_and_uses_strict_boundary():
    snap = Snapshot("E", date(2026, 8, 10), "R", "P", 165 / 7, 0, 0, 3, 0, 0, 3, None, (), False)
    row = naive_predict((snap,), (), PredictorConfig("1", "c", 0.05))[0]
    assert row.explanation_facts["projection_hours"] == 55
    assert row.will_breach is False and row.risk_score is None


def test_reference_six_week_parity_and_current_threshold():
    loaded = ingest_demo(".")
    shifts = source_shifts(loaded)
    history = build_history(shifts, loaded.employees_by_id, loaded.reporting.week_start)
    weeks, correlated, naive = replay(history, PredictorConfig("1.0", "correlated-hours-1.0", 0.05))
    assert len(weeks) == 6
    assert tuple(sum(getattr(w, field) for w in weeks) for field in
                 ("correlated_tp", "correlated_fp", "correlated_fn", "naive_tp", "naive_fp", "naive_fn")) == (24, 137, 20, 23, 260, 21)
    assert choose_threshold(correlated) == 0.05
    assert len(correlated) == len(naive) == 8 * len(loaded.employees_by_id)
    reconciled = reconcile_weekly_summary(loaded, build_outcomes(shifts, loaded.employees_by_id, loaded.reporting.week_start))
    assert sum(row.status == "matches" for row in reconciled) == 2122
    assert sum(row.status == "missing_summary" for row in reconciled) == 8
    new_register = dict(loaded.employees_by_id)
    new_register["NEW"] = {"role": "Security Officer", "shift_pattern": "4-on-4-off"}
    new_snapshot = next(row for row in build_snapshot(shifts, new_register, loaded.reporting.week_start) if row.employee_id == "NEW")
    forecast = correlated_predict((new_snapshot,), history, PredictorConfig("1.0", "correlated-hours-1.0", 0.05))[0]
    assert forecast.fallback and "peer_only" in forecast.fallback
    assert math.isfinite(forecast.risk_score)
    with pytest.raises(ProcessingError):
        correlated_predict((new_snapshot,), (), PredictorConfig("1.0", "correlated-hours-1.0", 0.05))


def test_ambiguous_shift_ids_do_not_add_hours_or_clean_labels():
    files = {
        "employees.csv": b"employee_id,full_name,primary_site_id,contract_ordinary_hours\nE,One,S,45\n",
        "sites.csv": b"site_id,site_name\nS,Site\n",
        "shifts.csv": b"shift_id,employee_id,site_id,shift_date,clock_in_time,clock_out_time\nA,E,S,2026-08-03,08:00,16:00\nA,E,S,2026-08-03,08:00,16:00\nB,E,S,2026-08-04,08:00,16:00\nC,E,S,2026-08-05,08:00,16:00\nD,E,S,2026-08-06,08:00,16:00\nF,E,S,2026-08-07,08:00,16:00\nG,E,S,2026-08-08,08:00,16:00\nH,E,S,2026-08-09,08:00,16:00\nI,E,S,2026-08-12,08:00,16:00\n",
    }
    loaded = ingest(files)
    shifts = source_shifts(loaded)
    assert sum(s.excluded_reason == "ambiguous_shift_id" for s in shifts) == 2
    outcome = next(o for o in build_outcomes(shifts, loaded.employees_by_id, date(2026, 8, 10)) if o.week_start == date(2026, 8, 3))
    assert outcome.recorded_hours == 48
    assert not outcome.label_eligible and "invalid_time" in outcome.exclusion_reasons
