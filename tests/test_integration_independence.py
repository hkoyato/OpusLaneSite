"""Integration test for cross-station independence (Task 14.5).

Verifies that a failing request for one station does not block storage for
another station. Two scenarios are tested:

1. A malformed/invalid snapshot for station_b returns 422 but does not affect
   the already-stored snapshot for station_a or the subsequently stored
   snapshot for station_c.
2. A faulting store that raises only for a specific station_id ("broken_station")
   returns 503 for that station but does not block successful storage for other
   stations submitted before and after the fault.

Validates: Requirements 6.4
"""

from __future__ import annotations

import pytest

from station_stats_api.http_result import (
    HTTP_CREATED,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_UNPROCESSABLE_ENTITY,
)
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.snapshot_handler import handle_snapshot
from station_stats_api.store import PutOutcome

import json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_snapshot(station_id: str, ts_offset: int = 0) -> dict:
    """Return a valid Station_Metric_Snapshot for the given station_id."""
    return {
        "station_id": station_id,
        "timestamp": f"2026-06-12T14:{ts_offset:02d}:00Z",
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


def _submit(store, snapshot: dict):
    """Submit a snapshot through handle_snapshot and return the HttpResult."""
    raw_body = json.dumps(snapshot).encode("utf-8")
    return handle_snapshot(raw_body, store, log_sink=lambda _entry: None)


# ---------------------------------------------------------------------------
# Faulting store that raises only for a specific station_id
# ---------------------------------------------------------------------------


class FaultingStore(InMemoryStatisticsStore):
    """An InMemoryStatisticsStore that raises on put_if_newer for a specific station.

    All other stations are stored normally. This simulates a partial storage
    fault isolated to one station (e.g. a DynamoDB partition error).
    """

    def __init__(self, fault_station_id: str) -> None:
        super().__init__()
        self._fault_station_id = fault_station_id

    def put_if_newer(self, snapshot: dict) -> PutOutcome:
        if snapshot["station_id"] == self._fault_station_id:
            raise RuntimeError("simulated storage fault for broken_station")
        return super().put_if_newer(snapshot)


# ---------------------------------------------------------------------------
# Test 1: Valid -> Invalid -> Valid (malformed snapshot does not block others)
# ---------------------------------------------------------------------------


def test_invalid_snapshot_for_one_station_does_not_block_others():
    """A 422 rejection for station_b does not affect station_a or station_c.

    Validates: Requirements 6.4
    """
    store = InMemoryStatisticsStore()

    # Submit valid snapshot for station_a → 201
    snapshot_a = _valid_snapshot("station_a", ts_offset=1)
    result_a = _submit(store, snapshot_a)
    assert result_a.status_code == HTTP_CREATED

    # Submit an INVALID snapshot for station_b (missing required fields) → 422
    invalid_snapshot_b = {
        "station_id": "station_b",
        "timestamp": "2026-06-12T14:02:00Z",
        # Missing all numeric fields → validation failure
    }
    result_b = _submit(store, invalid_snapshot_b)
    assert result_b.status_code == HTTP_UNPROCESSABLE_ENTITY

    # Submit valid snapshot for station_c → 201
    snapshot_c = _valid_snapshot("station_c", ts_offset=3)
    result_c = _submit(store, snapshot_c)
    assert result_c.status_code == HTTP_CREATED

    # station_a is still stored and retrievable
    stored_a = store.get("station_a")
    assert stored_a is not None
    assert stored_a["station_id"] == "station_a"
    assert stored_a == snapshot_a

    # station_c is stored and retrievable
    stored_c = store.get("station_c")
    assert stored_c is not None
    assert stored_c["station_id"] == "station_c"
    assert stored_c == snapshot_c

    # station_b was never stored (rejected)
    assert store.get("station_b") is None


# ---------------------------------------------------------------------------
# Test 2: Faulting store (storage error for one station does not block others)
# ---------------------------------------------------------------------------


def test_storage_fault_for_one_station_does_not_block_others():
    """A 503 storage error for broken_station does not affect working stations.

    Validates: Requirements 6.4
    """
    store = FaultingStore(fault_station_id="broken_station")

    # Submit valid snapshot for working_station_1 → 201
    snapshot_1 = _valid_snapshot("working_station_1", ts_offset=1)
    result_1 = _submit(store, snapshot_1)
    assert result_1.status_code == HTTP_CREATED

    # Submit valid snapshot for broken_station → 503 (storage fault)
    snapshot_broken = _valid_snapshot("broken_station", ts_offset=2)
    result_broken = _submit(store, snapshot_broken)
    assert result_broken.status_code == HTTP_SERVICE_UNAVAILABLE

    # Submit valid snapshot for working_station_2 → 201
    snapshot_2 = _valid_snapshot("working_station_2", ts_offset=3)
    result_2 = _submit(store, snapshot_2)
    assert result_2.status_code == HTTP_CREATED

    # working_station_1 is stored and retrievable
    stored_1 = store.get("working_station_1")
    assert stored_1 is not None
    assert stored_1 == snapshot_1

    # working_station_2 is stored and retrievable
    stored_2 = store.get("working_station_2")
    assert stored_2 is not None
    assert stored_2 == snapshot_2

    # broken_station has nothing stored (fault prevented persistence)
    assert store.get("broken_station") is None

    # The failure of broken_station did not alter the store's ability to serve
    # the other two stations via the list index
    index = store.list_index()
    stored_ids = {sid for sid, _ in index}
    assert stored_ids == {"working_station_1", "working_station_2"}
