"""Property-based test for idempotent snapshot resubmission.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the ``Statistics_Store``. The component
under test, ``station_stats_api.memory_store.InMemoryStatisticsStore``, is the
in-memory fake that implements the same last-write-wins-by-UTC-instant
semantics as the DynamoDB-backed adapter, so this test runs headless and
cheaply across many generated inputs.

Per the design's duplicate definition, a resubmission with the same
``(station_id, timestamp)`` instant *and* identical snapshot content is an
idempotent duplicate: ``put_if_newer`` returns ``PutOutcome.DUPLICATE`` and the
stored snapshot is left unchanged, with no conflicting or duplicate record
created.

Validates: Requirements 8.8
"""

from __future__ import annotations

from datetime import datetime

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.store import PutOutcome
from station_stats_api.validation import INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Strategies — generate well-formed snapshots (mirrors test_validation_property)
# ---------------------------------------------------------------------------

# Valid station_id / slowest_lane_id: 1-64 chars of [a-z0-9_-].
_valid_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

_valid_integer_strategy = st.one_of(
    st.sampled_from([0, 1, 1_000_000]),
    st.integers(min_value=0, max_value=1_000_000),
)

_valid_minute_strategy = st.one_of(
    st.sampled_from([0, 1, 1.0, 100_000, 100_000.0]),
    st.integers(min_value=0, max_value=100_000),
    st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
)

_valid_confidence_strategy = st.one_of(
    st.sampled_from([0, 1, 1.0, 0.0]),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)

_valid_slowest_lane_strategy = st.one_of(st.none(), _valid_id_strategy)


@st.composite
def _iso_timestamp(draw: st.DrawFn) -> str:
    """Generate a valid ISO 8601 timestamp with an explicit offset or ``Z``."""
    base = draw(
        st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1))
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
    """Build 0-4 snapshots for unrelated stations distinct from the subject.

    These confirm that resubmitting the subject snapshot does not disturb any
    other station's stored record.
    """
    station_ids = draw(
        st.lists(_valid_id_strategy, min_size=0, max_size=4, unique=True)
    )
    return [draw(_well_formed_snapshot(station_id=sid)) for sid in station_ids]


# ---------------------------------------------------------------------------
# Property 10: Resubmitting a stored snapshot is idempotent
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 10: Resubmitting a stored snapshot is idempotent


@settings(max_examples=200)
@given(
    snapshot=_well_formed_snapshot(),
    others=_distinct_station_snapshots(),
    resubmissions=st.integers(min_value=1, max_value=5),
)
def test_resubmitting_a_stored_snapshot_is_idempotent(
    snapshot: dict, others: list[dict], resubmissions: int
) -> None:
    """**Validates: Requirements 8.8**

    For any snapshot already stored (first ``put_if_newer`` returns STORED),
    resubmitting a snapshot with the same ``station_id``, the same ``timestamp``
    instant, and identical content one or more times: each resubmission returns
    ``PutOutcome.DUPLICATE``, the stored current snapshot is unchanged (equal to
    the originally stored snapshot), and the store's index still has exactly one
    entry for that station (no conflicting/duplicate record). Unrelated stations
    are untouched.
    """
    station_id = snapshot["station_id"]
    # Unrelated stations must be genuinely distinct from the subject.
    others = [o for o in others if o["station_id"] != station_id]

    store = InMemoryStatisticsStore()

    # Seed unrelated stations first; capture their stored state for comparison.
    for other in others:
        assert store.put_if_newer(other) is PutOutcome.STORED
    other_state_before = {o["station_id"]: store.get(o["station_id"]) for o in others}

    # First store of the subject snapshot succeeds.
    assert store.put_if_newer(snapshot) is PutOutcome.STORED
    originally_stored = store.get(station_id)
    assert originally_stored == snapshot

    index_entries_for_station_before = [
        entry for entry in store.list_index() if entry[0] == station_id
    ]
    assert len(index_entries_for_station_before) == 1

    # Resubmit the identical snapshot one or more times.
    for _ in range(resubmissions):
        # Pass a fresh copy so the store cannot rely on object identity.
        outcome = store.put_if_newer(dict(snapshot))

        # Each resubmission is recognized as an idempotent duplicate.
        assert outcome is PutOutcome.DUPLICATE
        # The stored current snapshot is unchanged.
        assert store.get(station_id) == originally_stored
        # Still exactly one index entry for that station: no conflicting record.
        index_entries = [e for e in store.list_index() if e[0] == station_id]
        assert len(index_entries) == 1
        assert index_entries[0] == (station_id, snapshot["timestamp"])

    # Unrelated stations are completely unaffected by the resubmissions.
    for other_id, before in other_state_before.items():
        assert store.get(other_id) == before
