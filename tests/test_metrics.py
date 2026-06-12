"""Tests for the station wait-time formula and metrics aggregation.

Covers the deterministic intelligence layer in ``gui/metrics.py``: the public
wait-time formula, status classification, peak-concurrency queue-depth proxy,
throughput, and the full station-metrics aggregation. Includes property-based
invariants (Hypothesis) alongside concrete examples.
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from gui.metrics import (
    STATUS_ATTENTION,
    STATUS_MODERATE,
    STATUS_NORMAL,
    STATUS_UNKNOWN,
    StationMetrics,
    classify_status,
    compute_station_metrics,
    compute_throughput_per_hour,
    estimate_public_wait,
    peak_concurrent_vehicles,
    round_public_wait,
)
from gui.models import TrackResult


def _track(
    vehicle_id: int,
    enter_time: float,
    leave_time: float | None,
    *,
    fps: float = 30.0,
) -> TrackResult:
    """Build a TrackResult with consistent frame/time fields for tests."""
    first_frame = int(round(enter_time * fps))
    if leave_time is None:
        last_frame = first_frame
        wait_time = None
    else:
        last_frame = int(round(leave_time * fps))
        wait_time = leave_time - enter_time
    return TrackResult(
        vehicle_id=vehicle_id,
        plate_text="",
        plate_confidence=0.0,
        first_frame=first_frame,
        last_frame=last_frame,
        enter_time=enter_time,
        leave_time=leave_time,
        wait_time=wait_time,
    )


# ---------------------------------------------------------------------------
# estimate_public_wait
# ---------------------------------------------------------------------------


def test_estimate_public_wait_formula_example():
    # Product overview worked example: 9 vehicles * 6.2 min / 3 lanes = 18.6
    assert estimate_public_wait(9, 6.2, 3) == 18.6


def test_estimate_public_wait_empty_queue_is_zero():
    assert estimate_public_wait(0, 6.2, 3) == 0.0


def test_estimate_public_wait_zero_inspection_is_zero():
    assert estimate_public_wait(5, 0.0, 3) == 0.0


def test_estimate_public_wait_zero_lanes_treated_as_one():
    # active_lanes floored at 1 to avoid division by zero.
    assert estimate_public_wait(4, 5.0, 0) == 20.0


@settings(max_examples=100)
@given(
    queue_depth=st.integers(min_value=0, max_value=200),
    avg_inspection=st.floats(
        min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False
    ),
    active_lanes=st.integers(min_value=0, max_value=20),
)
def test_estimate_public_wait_non_negative(queue_depth, avg_inspection, active_lanes):
    result = estimate_public_wait(queue_depth, avg_inspection, active_lanes)
    assert result >= 0.0


@settings(max_examples=100)
@given(
    queue_depth=st.integers(min_value=1, max_value=200),
    avg_inspection=st.floats(
        min_value=0.1, max_value=120.0, allow_nan=False, allow_infinity=False
    ),
    active_lanes=st.integers(min_value=1, max_value=20),
)
def test_estimate_public_wait_matches_formula(queue_depth, avg_inspection, active_lanes):
    expected = queue_depth * avg_inspection / active_lanes
    assert estimate_public_wait(queue_depth, avg_inspection, active_lanes) == expected


# ---------------------------------------------------------------------------
# round_public_wait
# ---------------------------------------------------------------------------


def test_round_public_wait_rounds_to_whole_minutes():
    assert round_public_wait(18.6) == 19
    assert round_public_wait(18.42) == 18


def test_round_public_wait_zero_stays_zero():
    assert round_public_wait(0.0) == 0


def test_round_public_wait_small_positive_floored_to_one():
    # Never show "0 minutes" while vehicles are still queueing.
    assert round_public_wait(0.3) == 1


# ---------------------------------------------------------------------------
# classify_status
# ---------------------------------------------------------------------------


def test_classify_status_none_is_unknown():
    key, label = classify_status(None)
    assert key == STATUS_UNKNOWN
    assert label == "Data unavailable"


def test_classify_status_thresholds():
    assert classify_status(0.0)[0] == STATUS_NORMAL
    assert classify_status(9.99)[0] == STATUS_NORMAL
    assert classify_status(10.0)[0] == STATUS_MODERATE
    assert classify_status(19.99)[0] == STATUS_MODERATE
    assert classify_status(20.0)[0] == STATUS_ATTENTION
    assert classify_status(45.0)[0] == STATUS_ATTENTION


# ---------------------------------------------------------------------------
# peak_concurrent_vehicles
# ---------------------------------------------------------------------------


def test_peak_concurrent_empty_is_zero():
    assert peak_concurrent_vehicles([]) == 0


def test_peak_concurrent_overlapping():
    # Three vehicles all present between t=2 and t=3 => peak 3.
    results = [
        _track(1, 0.0, 3.0),
        _track(2, 1.0, 4.0),
        _track(3, 2.0, 5.0),
    ]
    assert peak_concurrent_vehicles(results) == 3


def test_peak_concurrent_sequential_no_overlap():
    # Back-to-back vehicles (leave processed before next enter at same ts).
    results = [
        _track(1, 0.0, 1.0),
        _track(2, 1.0, 2.0),
        _track(3, 2.0, 3.0),
    ]
    assert peak_concurrent_vehicles(results) == 1


def test_peak_concurrent_still_present_counts_to_end():
    results = [
        _track(1, 0.0, None),  # never leaves
        _track(2, 1.0, 2.0),
        _track(3, 3.0, 4.0),
    ]
    # Vehicle 1 present through end (t=4): overlaps 2 (t1-2) and 3 (t3-4).
    assert peak_concurrent_vehicles(results) == 2


# ---------------------------------------------------------------------------
# compute_throughput_per_hour
# ---------------------------------------------------------------------------


def test_throughput_per_hour_basic():
    # 10 vehicles in 600s (10 min) => 60/hour.
    assert compute_throughput_per_hour(10, 600.0) == 60.0


def test_throughput_per_hour_zero_duration():
    assert compute_throughput_per_hour(5, 0.0) == 0.0


# ---------------------------------------------------------------------------
# compute_station_metrics
# ---------------------------------------------------------------------------


def test_compute_station_metrics_empty():
    m = compute_station_metrics([])
    assert isinstance(m, StationMetrics)
    assert m.total_vehicles == 0
    assert m.vehicles_in_queue == 0
    assert m.completed_vehicles == 0
    assert m.average_inspection_minutes is None
    assert m.estimated_public_wait_minutes is None
    assert m.status == STATUS_UNKNOWN
    assert m.throughput_per_hour == 0.0


def test_compute_station_metrics_grounded_example():
    # Four vehicles each taking 360s (6 min), overlapping for a peak of 4.
    results = [
        _track(1, 0.0, 360.0),
        _track(2, 0.0, 360.0),
        _track(3, 0.0, 360.0),
        _track(4, 0.0, 360.0),
    ]
    m = compute_station_metrics(results, active_lanes=2)
    assert m.total_vehicles == 4
    assert m.completed_vehicles == 4
    assert m.vehicles_in_queue == 4
    assert m.average_inspection_minutes == 6.0
    # 4 * 6 / 2 = 12 minutes -> moderate
    assert m.estimated_public_wait_minutes == 12
    assert m.status == STATUS_MODERATE


def test_compute_station_metrics_active_lanes_floored():
    results = [_track(1, 0.0, 120.0), _track(2, 0.0, 120.0)]
    m = compute_station_metrics(results, active_lanes=0)
    assert m.active_lanes == 1


def test_compute_station_metrics_to_dict_serialisable():
    results = [_track(1, 0.0, 300.0), _track(2, 1.0, 301.0)]
    d = compute_station_metrics(results).to_dict()
    assert d["station_name"] == "Demo Inspection Station"
    assert set(d).issuperset(
        {
            "total_vehicles",
            "vehicles_in_queue",
            "estimated_public_wait_minutes",
            "throughput_per_hour",
            "status",
            "status_label",
        }
    )


def test_compute_station_metrics_explicit_duration_throughput():
    results = [_track(i, 0.0, 60.0) for i in range(6)]
    # 6 completed over an explicit 3600s window => 6/hour.
    m = compute_station_metrics(results, observed_duration_seconds=3600.0)
    assert m.throughput_per_hour == 6.0
    assert m.observed_duration_minutes == 60.0
