"""Load tests for scale and latency (Task 14.6).

These are LOCAL load tests against the in-memory store and the Lambda adapter.
They prove the application logic handles the supported scale without errors.
Actual p95 latency against DynamoDB is infrastructure-dependent and measured in
deployed integration testing.

Validates: Requirements 6.1, 6.2, 6.3
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from station_stats_api.http_result import HTTP_CREATED
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.snapshot_handler import handle_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_snapshot(station_id: str, minute: int = 0, second: int = 0) -> dict:
    """Return a valid Station_Metric_Snapshot for the given station_id."""
    return {
        "station_id": station_id,
        "timestamp": f"2026-06-12T14:{minute:02d}:{second:02d}Z",
        "vehicles_in_queue": 5,
        "vehicles_in_bay": 2,
        "active_lanes": 3,
        "average_queue_wait_minutes": 12.0,
        "average_inspection_minutes": 6.5,
        "estimated_public_wait_minutes": 18.0,
        "throughput_per_hour": 25,
        "slowest_lane_id": "lane_1",
        "confidence_score": 0.85,
    }


def _submit(store: InMemoryStatisticsStore, snapshot: dict):
    """Submit a snapshot through handle_snapshot and return the HttpResult."""
    raw_body = json.dumps(snapshot).encode("utf-8")
    return handle_snapshot(raw_body, store, log_sink=lambda _entry: None)


# ---------------------------------------------------------------------------
# Test 1: 50 stations submitting within 60s succeed (Req 6.1)
# ---------------------------------------------------------------------------


def test_50_stations_within_60s():
    """50 distinct stations each submit one snapshot; all return 201 and complete
    within 60s total wall time. All 50 stations are retrievable afterwards.

    Validates: Requirement 6.1
    """
    store = InMemoryStatisticsStore()
    station_count = 50

    snapshots = [
        _valid_snapshot(f"station_{i:03d}", minute=i % 60)
        for i in range(station_count)
    ]

    start = time.perf_counter()
    results = [_submit(store, snap) for snap in snapshots]
    elapsed = time.perf_counter() - start

    # All return 201
    for i, result in enumerate(results):
        assert result.status_code == HTTP_CREATED, (
            f"station_{i:03d} returned {result.status_code}, expected 201"
        )

    # Total time under 60s
    assert elapsed < 60.0, f"Total elapsed {elapsed:.2f}s exceeds 60s limit"

    # All 50 stations retrievable
    for i in range(station_count):
        stored = store.get(f"station_{i:03d}")
        assert stored is not None, f"station_{i:03d} not retrievable after submission"
        assert stored["station_id"] == f"station_{i:03d}"


# ---------------------------------------------------------------------------
# Test 2: p95 latency under concurrent load (Req 6.2)
# ---------------------------------------------------------------------------


def test_p95_latency_under_concurrent_load():
    """Submit 50+ requests concurrently using a thread pool. Measure each
    request's wall time and assert p95 < 2000ms.

    Against the in-memory store this validates the handler logic doesn't have
    blocking pathology.

    Validates: Requirement 6.2
    """
    store = InMemoryStatisticsStore()
    request_count = 60  # > 50 to exceed the supported station count

    snapshots = [
        _valid_snapshot(f"concurrent_{i:03d}", minute=i % 60)
        for i in range(request_count)
    ]

    latencies_ms: list[float] = []

    def submit_one(snapshot: dict) -> tuple[int, float]:
        """Submit one snapshot and return (status_code, latency_ms)."""
        raw_body = json.dumps(snapshot).encode("utf-8")
        t0 = time.perf_counter()
        result = handle_snapshot(raw_body, store, log_sink=lambda _: None)
        t1 = time.perf_counter()
        latency = (t1 - t0) * 1000.0
        return result.status_code, latency

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(submit_one, snap): i
            for i, snap in enumerate(snapshots)
        }
        for future in as_completed(futures):
            status_code, latency = future.result()
            assert status_code == HTTP_CREATED, (
                f"Request returned {status_code}, expected 201"
            )
            latencies_ms.append(latency)

    # Compute p95
    latencies_ms.sort()
    p95_index = int(len(latencies_ms) * 0.95) - 1
    p95_latency = latencies_ms[p95_index]

    assert p95_latency < 2000.0, (
        f"p95 latency is {p95_latency:.2f}ms, exceeds 2000ms limit"
    )


# ---------------------------------------------------------------------------
# Test 3: 100 stations with no schema change (Req 6.3)
# ---------------------------------------------------------------------------


def test_100_stations_no_schema_change():
    """Submit 100 distinct station snapshots (twice the Supported_Station_Count).
    All return 201 and all are retrievable. No schema change is needed for the
    store to handle >50 stations.

    Validates: Requirement 6.3
    """
    store = InMemoryStatisticsStore()
    station_count = 100

    snapshots = [
        _valid_snapshot(f"scale_{i:04d}", minute=i % 60, second=i % 60)
        for i in range(station_count)
    ]

    for i, snap in enumerate(snapshots):
        result = _submit(store, snap)
        assert result.status_code == HTTP_CREATED, (
            f"scale_{i:04d} returned {result.status_code}, expected 201"
        )

    # All 100 stations are retrievable
    for i in range(station_count):
        station_id = f"scale_{i:04d}"
        stored = store.get(station_id)
        assert stored is not None, f"{station_id} not retrievable"
        assert stored["station_id"] == station_id

    # list_index returns all 100
    index = store.list_index()
    assert len(index) == station_count
