"""Property-based test for accepting and storing valid snapshots.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the Snapshot (POST) handler
(``station_stats_api.snapshot_handler.handle_snapshot``). The handler, the
in-memory ``StatisticsStore`` fake, and the metrics read path are all pure
logic over already-parsed data, so this test runs headless and cheaply across
many generated inputs.

Validates: Requirements 1.2, 1.4
"""

from __future__ import annotations

import json
from datetime import datetime

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.http_result import HTTP_CREATED, HTTP_OK
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.metrics_handler import get_station
from station_stats_api.snapshot_handler import handle_snapshot
from station_stats_api.validation import INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Strategies — reuse the valid-snapshot pattern from test_validation_property.py
# ---------------------------------------------------------------------------

# Valid station_id / slowest_lane_id: 1-64 chars of [a-z0-9_-].
_valid_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

# Integer fields in [0, 1_000_000], mixing boundary values with in-range ints.
_valid_integer_strategy = st.one_of(
    st.sampled_from([0, 1, 1_000_000]),
    st.integers(min_value=0, max_value=1_000_000),
)

# Minute fields in [0, 100_000]: boundaries plus arbitrary in-range numbers.
_valid_minute_strategy = st.one_of(
    st.sampled_from([0, 1, 1.0, 100_000, 100_000.0]),
    st.integers(min_value=0, max_value=100_000),
    st.floats(
        min_value=0,
        max_value=100_000,
        allow_nan=False,
        allow_infinity=False,
    ),
)

# confidence_score in [0, 1]: boundaries plus in-range floats.
_valid_confidence_strategy = st.one_of(
    st.sampled_from([0, 1, 1.0, 0.0]),
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
def _well_formed_snapshot(draw: st.DrawFn) -> dict:
    """Build a snapshot whose every field satisfies the Requirement 2 rules."""
    snapshot: dict = {
        "station_id": draw(_valid_id_strategy),
        "timestamp": draw(_iso_timestamp()),
        "slowest_lane_id": draw(_valid_slowest_lane_strategy),
        "confidence_score": draw(_valid_confidence_strategy),
    }
    for field in INTEGER_FIELDS:
        snapshot[field] = draw(_valid_integer_strategy)
    for field in MINUTE_FIELDS:
        snapshot[field] = draw(_valid_minute_strategy)
    return snapshot


# ---------------------------------------------------------------------------
# Property 1: Valid snapshots are accepted and stored
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 1: Valid snapshots are accepted and stored


@settings(max_examples=200)
@given(snapshot=_well_formed_snapshot())
def test_valid_snapshots_are_accepted_and_stored(snapshot: dict) -> None:
    """**Validates: Requirements 1.2, 1.4**

    For any Station_Metric_Snapshot whose fields all satisfy the Requirement 2
    validation rules, handling a POST of that snapshot against a fresh store
    returns HTTP 201 (Req 1.2), with a body containing the station_id and the
    stored timestamp (Req 1.4); the snapshot then becomes retrievable through
    the metrics read path with HTTP 200 returning the stored snapshot.
    """
    store = InMemoryStatisticsStore()
    body = json.dumps(snapshot).encode()

    result = handle_snapshot(body, store)

    # A fresh store always stores a valid snapshot as the current one (Req 1.2).
    assert result.status_code == HTTP_CREATED
    # The response body echoes the station_id and stored timestamp (Req 1.4).
    assert isinstance(result.body, dict)
    assert result.body["station_id"] == snapshot["station_id"]
    assert result.body["timestamp"] == snapshot["timestamp"]

    # The accepted snapshot is now retrievable for that station.
    read = get_station(snapshot["station_id"], store)
    assert read.status_code == HTTP_OK
    assert isinstance(read.body, dict)
    # The stored snapshot carries the submitted station_id and timestamp.
    assert read.body["station_id"] == snapshot["station_id"]
    assert read.body["timestamp"] == snapshot["timestamp"]
