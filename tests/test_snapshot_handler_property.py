"""Property-based test for handle_snapshot accept-and-store behavior.

Uses Hypothesis to verify that valid snapshots are accepted (HTTP 201) and
stored with all fields preserved, and that the response body echoes the
station_id and timestamp as stored.

Validates: Requirements 1.2, 1.4
"""

from __future__ import annotations

import json
from datetime import datetime

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.snapshot_handler import handle_snapshot
from station_stats_api.validation import GLOSSARY_FIELDS, INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 1: Valid snapshots are accepted and stored
# ---------------------------------------------------------------------------

# --- Strategies (reused from test_validation_property.py patterns) ----------

_valid_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

_valid_integer_strategy = st.one_of(
    st.sampled_from([0, 1, 1_000_000]),
    st.integers(min_value=0, max_value=1_000_000),
)

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

_valid_confidence_strategy = st.one_of(
    st.sampled_from([0, 1, 1.0, 0.0]),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)

_valid_slowest_lane_strategy = st.one_of(st.none(), _valid_id_strategy)


@st.composite
def _iso_timestamp(draw: st.DrawFn) -> str:
    """Generate a valid ISO 8601 timestamp with an explicit offset or Z."""
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
    """Build a snapshot whose every field satisfies Requirement 2 rules."""
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
# Property test
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(snapshot=_well_formed_snapshot())
def test_valid_snapshots_are_accepted_and_stored(snapshot: dict) -> None:
    """**Validates: Requirements 1.2, 1.4**

    For any Station_Metric_Snapshot whose fields all satisfy the Requirement 2
    validation rules, calling handle_snapshot returns HTTP 201, the response
    body contains the station_id and timestamp matching the submitted values,
    and the store contains the snapshot with all fields preserved.
    """
    store = InMemoryStatisticsStore()
    raw_body = json.dumps(snapshot).encode("utf-8")

    result = handle_snapshot(raw_body, store)

    # Req 1.2: valid snapshot -> 201
    assert result.status_code == 201, (
        f"Expected 201, got {result.status_code}: {result.body}"
    )

    # Req 1.4: response body contains station_id and timestamp as stored
    assert result.body is not None
    assert result.body["station_id"] == snapshot["station_id"]
    assert result.body["timestamp"] == snapshot["timestamp"]

    # The snapshot is retrievable from the store with all fields preserved
    stored = store.get(snapshot["station_id"])
    assert stored is not None, "Snapshot was not stored"
    for field in GLOSSARY_FIELDS:
        assert stored[field] == snapshot[field], (
            f"Field {field!r}: stored={stored[field]!r} != submitted={snapshot[field]!r}"
        )
