"""Property-based test for the list endpoint reflecting stored stations.

Uses Hypothesis to verify that the list endpoint returns exactly the
``station_id`` and ``timestamp`` of every station that has a stored snapshot,
and returns an empty list when no station has a snapshot.

The component under test is ``station_stats_api.metrics_handler.list_stations``
backed by the in-memory ``InMemoryStatisticsStore`` fake so the test runs
headless and cheaply across many generated inputs.

Validates: Requirements 5.4, 5.6
"""

from __future__ import annotations

from datetime import datetime

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from station_stats_api.http_result import HTTP_OK
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.metrics_handler import list_stations
from station_stats_api.timestamps import to_utc_instant
from station_stats_api.validation import INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid station_id: 1-64 chars of [a-z0-9_-].
_valid_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

# Integer fields in [0, 1_000_000].
_valid_integer_strategy = st.one_of(
    st.sampled_from([0, 1, 1_000_000]),
    st.integers(min_value=0, max_value=1_000_000),
)

# Minute fields in [0, 100_000].
_valid_minute_strategy = st.one_of(
    st.sampled_from([0, 1, 100_000]),
    st.integers(min_value=0, max_value=100_000),
    st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
)

# confidence_score in [0, 1].
_valid_confidence_strategy = st.one_of(
    st.sampled_from([0, 1, 0.0, 1.0]),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)

# slowest_lane_id is optional: null or a well-formed identifier.
_valid_slowest_lane_strategy = st.one_of(st.none(), _valid_id_strategy)


@st.composite
def _iso_timestamp(draw: st.DrawFn) -> str:
    """Generate a valid ISO 8601 timestamp with an explicit offset or ``Z``."""
    base = draw(
        st.datetimes(
            min_value=datetime(2000, 1, 1),
            max_value=datetime(2100, 1, 1),
        )
    )
    if draw(st.booleans()):
        return base.isoformat() + "Z"
    offset_minutes = draw(st.integers(min_value=-12 * 60, max_value=14 * 60))
    sign = "+" if offset_minutes >= 0 else "-"
    magnitude = abs(offset_minutes)
    return f"{base.isoformat()}{sign}{magnitude // 60:02d}:{magnitude % 60:02d}"


@st.composite
def _well_formed_snapshot(draw: st.DrawFn, station_id: str | None = None) -> dict:
    """Build a snapshot whose every field satisfies the Requirement 2 rules."""
    snapshot: dict = {
        "station_id": station_id if station_id is not None else draw(_valid_id_strategy),
        "timestamp": draw(_iso_timestamp()),
        "slowest_lane_id": draw(_valid_slowest_lane_strategy),
        "confidence_score": draw(_valid_confidence_strategy),
    }
    for field in INTEGER_FIELDS:
        snapshot[field] = draw(_valid_integer_strategy)
    for field in MINUTE_FIELDS:
        snapshot[field] = draw(_valid_minute_strategy)
    return snapshot


@st.composite
def _distinct_station_snapshots(draw: st.DrawFn) -> list[dict]:
    """Generate a set of valid snapshots with distinct station_ids.

    Each station_id is unique so that every snapshot stored becomes the current
    snapshot for its station. This lets us assert that the list endpoint
    reflects exactly the stored stations.
    """
    # Generate 1 to 20 distinct station_ids.
    station_ids = draw(
        st.lists(_valid_id_strategy, min_size=1, max_size=20, unique=True)
    )
    snapshots = []
    for sid in station_ids:
        snapshot = draw(_well_formed_snapshot(station_id=sid))
        snapshots.append(snapshot)
    return snapshots


# ---------------------------------------------------------------------------
# Property 8: The list endpoint reflects exactly the stored stations
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 8: The list endpoint reflects exactly the stored stations


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(snapshots=_distinct_station_snapshots())
def test_list_endpoint_reflects_exactly_stored_stations(
    snapshots: list[dict],
) -> None:
    """**Validates: Requirements 5.4, 5.6**

    For any set of stored current snapshots with distinct station_ids, a GET
    without a Station_Identifier returns HTTP 200 and a list whose entries are
    exactly the station_id and current timestamp of every station that has a
    stored snapshot.
    """
    store = InMemoryStatisticsStore()

    # Store all snapshots.
    for snapshot in snapshots:
        store.put_if_newer(snapshot)

    # Call the list endpoint.
    result = list_stations(store)

    # Must return 200.
    assert result.status_code == HTTP_OK

    # The body must be a list.
    assert isinstance(result.body, list)

    # Build the expected set of (station_id, timestamp) pairs.
    expected = {(s["station_id"], s["timestamp"]) for s in snapshots}

    # Build the actual set from the response body.
    actual = set()
    for entry in result.body:
        assert "station_id" in entry
        assert "timestamp" in entry
        actual.add((entry["station_id"], entry["timestamp"]))

    # The list must reflect exactly the stored stations.
    assert actual == expected


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_empty_store_returns_empty_list(data: st.DataObject) -> None:
    """**Validates: Requirement 5.6**

    When no station has a stored current snapshot, the list endpoint returns
    HTTP 200 with an empty list.
    """
    store = InMemoryStatisticsStore()

    result = list_stations(store)

    assert result.status_code == HTTP_OK
    assert isinstance(result.body, list)
    assert result.body == []
