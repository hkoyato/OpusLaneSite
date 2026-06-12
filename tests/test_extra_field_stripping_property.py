"""Property-based test for extra-field stripping on snapshot ingestion.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the snapshot ingestion path. A valid
``Station_Metric_Snapshot`` extended with arbitrary additional keys not defined
in the Glossary must still be accepted (HTTP ``201``), and the stored snapshot
must contain exactly the Glossary-defined fields and none of the extra keys
(Requirement 2.7).

The components under test are the pure-logic seams exercised against the
in-memory fake store, so the test runs headless and cheaply across many
generated inputs:
- ``station_stats_api.snapshot_handler.handle_snapshot`` (parse -> validate ->
  strip -> store)
- ``station_stats_api.memory_store.InMemoryStatisticsStore`` (storage)
- ``station_stats_api.metrics_handler.get_station`` (read-back)

Validates: Requirements 2.7
"""

from __future__ import annotations

import json
from datetime import datetime

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.metrics_handler import get_station
from station_stats_api.snapshot_handler import handle_snapshot
from station_stats_api.validation import (
    GLOSSARY_FIELDS,
    INTEGER_FIELDS,
    MINUTE_FIELDS,
)

# ---------------------------------------------------------------------------
# Strategies — well-formed snapshot values (mirroring the validation rules)
# ---------------------------------------------------------------------------

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


# Arbitrary JSON-serializable values for the extra keys (none/bool/number/str,
# nested lists and string-keyed objects), so stripping is exercised against the
# full range of payloads a caller might attach.
_json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(), children, max_size=4),
    max_leaves=10,
)

# Extra key names that are NOT Glossary fields. Filtered so a generated key can
# never collide with (and thus overwrite) a real Glossary field.
_extra_key_strategy = st.text(min_size=1, max_size=32).filter(
    lambda key: key not in GLOSSARY_FIELDS
)

_extra_fields_strategy = st.dictionaries(
    _extra_key_strategy, _json_values, min_size=1, max_size=6
)


# ---------------------------------------------------------------------------
# Property 5: Extra fields are stripped and do not affect acceptance
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 5: Extra fields are stripped and do not affect acceptance


@settings(max_examples=200)
@given(snapshot=_well_formed_snapshot(), extra=_extra_fields_strategy)
def test_extra_fields_are_stripped_and_do_not_affect_acceptance(
    snapshot: dict, extra: dict
) -> None:
    """**Validates: Requirements 2.7**

    A valid snapshot extended with arbitrary keys not defined in the Glossary is
    still accepted with HTTP ``201``, and the stored snapshot retrievable via the
    metrics path contains exactly the Glossary-defined fields and none of the
    extra keys.
    """
    store = InMemoryStatisticsStore()

    # Extend the valid snapshot with the extra (non-Glossary) keys. The filter on
    # the key strategy guarantees no real Glossary field is overwritten.
    extended = {**snapshot, **extra}
    raw_body = json.dumps(extended).encode("utf-8")

    # Submit through the ingestion handler: still accepted despite extra keys.
    result = handle_snapshot(raw_body, store)
    assert result.status_code == 201
    assert result.body["station_id"] == snapshot["station_id"]
    assert result.body["timestamp"] == snapshot["timestamp"]

    # Read the stored snapshot back through the metrics path.
    read = get_station(snapshot["station_id"], store)
    assert read.status_code == 200
    stored = read.body

    # The stored snapshot holds exactly the Glossary fields — nothing extra.
    assert set(stored.keys()) == set(GLOSSARY_FIELDS)
    for key in extra:
        assert key not in stored
    # Glossary field values are preserved exactly as submitted.
    for field in GLOSSARY_FIELDS:
        assert stored[field] == snapshot[field]
