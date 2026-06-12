"""Property-based test for storage round-trip field preservation.

Uses Hypothesis to verify that storing a valid Station_Metric_Snapshot via
``handle_snapshot`` and reading it back via ``get_station`` preserves every
Glossary-defined field exactly as submitted.

The test exercises the full handler pipeline (parse -> validate -> strip ->
store -> read) against the in-memory ``InMemoryStatisticsStore`` fake, which
implements the same last-write-wins semantics as the DynamoDB adapter. No AWS
calls are made.

Validates: Requirements 1.3, 4.1, 5.1, 5.3
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
from station_stats_api.validation import GLOSSARY_FIELDS, INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Strategies — valid snapshot generation
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
# Property 2: Storage and retrieval preserve every field
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 2: Storage and retrieval preserve every field


@settings(max_examples=200)
@given(snapshot=_well_formed_snapshot())
def test_storage_and_retrieval_preserve_every_field(snapshot: dict) -> None:
    """**Validates: Requirements 1.3, 4.1, 5.1, 5.3**

    For any valid Station_Metric_Snapshot, after it is stored via
    handle_snapshot and then read back through get_station, the returned
    snapshot contains the same values for station_id, timestamp,
    vehicles_in_queue, vehicles_in_bay, active_lanes,
    average_queue_wait_minutes, average_inspection_minutes,
    estimated_public_wait_minutes, throughput_per_hour, slowest_lane_id, and
    confidence_score that were submitted (storage round-trip).
    """
    store = InMemoryStatisticsStore()
    body = json.dumps(snapshot).encode()

    # Store via the snapshot handler.
    post_result = handle_snapshot(body, store)
    assert post_result.status_code == HTTP_CREATED

    # Read back via the metrics handler.
    read_result = get_station(snapshot["station_id"], store)
    assert read_result.status_code == HTTP_OK
    assert isinstance(read_result.body, dict)

    # Assert every Glossary field is preserved exactly as submitted.
    for field in GLOSSARY_FIELDS:
        assert read_result.body[field] == snapshot[field], (
            f"Field {field!r} not preserved: "
            f"submitted={snapshot[field]!r}, got={read_result.body.get(field)!r}"
        )
