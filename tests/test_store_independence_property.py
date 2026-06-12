"""Property-based test for per-station independence in the Statistics_Store.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the ``StatisticsStore`` adapter. The unit
under test is the in-memory fake
(``station_stats_api.memory_store.InMemoryStatisticsStore``), which applies the
same last-write-wins-per-station semantics the DynamoDB adapter implements, so
this test runs headless and cheaply across many generated inputs with no AWS
calls.

Validates: Requirements 4.4, 4.5, 6.4
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore

# The Supported_Station_Count for the initial deployment (Requirement 4.5).
SUPPORTED_STATION_COUNT = 50

# A fixed reference instant; per-station timestamps are derived from it so each
# station's snapshot carries a deterministic, distinct timestamp string.
_BASE_INSTANT = datetime(2026, 6, 12, 13, 45, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _snapshot_for(station_id: str, seed: int, second_offset: int) -> dict:
    """Build a valid snapshot for ``station_id`` derived from a single ``seed``.

    Field values are computed deterministically from ``seed`` so the whole
    collection of 50+ snapshots needs only one drawn integer per station — this
    keeps Hypothesis input generation cheap while still exercising independence
    across distinct station ids and distinct stored payloads.

    ``second_offset`` shifts the timestamp off the reference instant so updated
    snapshots can be given a strictly later instant than the original.
    """
    instant = _BASE_INSTANT + timedelta(seconds=second_offset)
    return {
        "station_id": station_id,
        "timestamp": instant.isoformat().replace("+00:00", "Z"),
        "vehicles_in_queue": seed % 1_000_001,
        "vehicles_in_bay": (seed * 3) % 1_000_001,
        "active_lanes": (seed * 7) % 1_001,
        "average_queue_wait_minutes": float(seed % 100_001),
        "average_inspection_minutes": float((seed * 2) % 100_001),
        "estimated_public_wait_minutes": float((seed * 5) % 100_001),
        "throughput_per_hour": (seed * 11) % 1_000_001,
        "slowest_lane_id": None if seed % 2 == 0 else f"lane_{seed % 1000}",
        "confidence_score": (seed % 101) / 100.0,
    }


@st.composite
def _distinct_station_snapshots(draw: st.DrawFn) -> list[dict]:
    """Build a collection of valid snapshots spanning DISTINCT station ids.

    The collection size reaches and exceeds the Supported_Station_Count of 50
    (min 50, up to 120 distinct stations), with unique station ids generated as
    ``station_{i}`` from distinct integers and one drawn value seed per station.
    """
    pairs = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=100_000),
                st.integers(min_value=0, max_value=1_000_000),
            ),
            unique_by=lambda p: p[0],
            min_size=SUPPORTED_STATION_COUNT,
            max_size=120,
        )
    )
    return [_snapshot_for(f"station_{i}", seed, 0) for i, seed in pairs]


# ---------------------------------------------------------------------------
# Property 7: Stations are retained independently
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 7: Stations are retained independently


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(snapshots=_distinct_station_snapshots(), update_data=st.data())
def test_stations_are_retained_independently(
    snapshots: list[dict], update_data: st.DataObject
) -> None:
    """**Validates: Requirements 4.4, 4.5, 6.4**

    Storing a snapshot for one station never alters the stored snapshot of any
    other station, and every station with a stored snapshot (at and above the
    Supported_Station_Count of 50) remains independently retrievable.
    """
    store = InMemoryStatisticsStore()

    # Store one snapshot per distinct station.
    for snapshot in snapshots:
        store.put_if_newer(snapshot)

    station_ids = [s["station_id"] for s in snapshots]

    # Sanity: the generator produced at least the Supported_Station_Count of
    # distinct stations (Requirement 4.5).
    assert len(station_ids) == len(set(station_ids))
    assert len(station_ids) >= SUPPORTED_STATION_COUNT

    # Every station's get() returns exactly the snapshot stored for it, and all
    # stations are concurrently retrievable (Requirement 4.5).
    expected = {s["station_id"]: s for s in snapshots}
    for station_id, snapshot in expected.items():
        assert store.get(station_id) == snapshot

    # list_index() contains exactly the distinct station ids (Requirement 4.5).
    assert {sid for sid, _ in store.list_index()} == set(station_ids)
    assert len(store.list_index()) == len(station_ids)

    # Capture the full pre-update state for every station.
    before = {sid: store.get(sid) for sid in station_ids}

    # Store an additional, strictly-newer snapshot for exactly ONE station.
    target_id = update_data.draw(st.sampled_from(station_ids))
    target_seed = update_data.draw(st.integers(min_value=0, max_value=1_000_000))
    updated = _snapshot_for(target_id, target_seed, 60)
    store.put_if_newer(updated)

    # Every OTHER station's stored snapshot is unchanged (Requirement 4.4).
    for sid in station_ids:
        if sid == target_id:
            continue
        assert store.get(sid) == before[sid]

    # The targeted station now reflects the strictly-newer update, confirming
    # the write that left the others untouched actually took effect.
    assert store.get(target_id) == updated

    # The set of retained stations is unchanged by an update to one station
    # (Requirements 4.4, 4.5).
    assert {sid for sid, _ in store.list_index()} == set(station_ids)
