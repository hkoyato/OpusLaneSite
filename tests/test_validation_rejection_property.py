"""Property-based test for snapshot rejection field-naming.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the validator. The function under test,
``station_stats_api.validation.validate_snapshot``, is pure (no I/O), so the
test runs headless and cheaply across many generated inputs.

The strategy starts from a fully valid ``Station_Metric_Snapshot``, chooses a
non-empty subset of fields to violate, injects a known invalid value (or removes
the key) into each chosen field while tracking the exact expected failing set,
and asserts the validator names exactly that set, reports the snapshot invalid,
and yields no ``cleaned`` payload (nothing to store).

Validates: Requirements 2.6
"""

from __future__ import annotations

import datetime as _dt

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.validation import (
    GLOSSARY_FIELDS,
    INTEGER_FIELDS,
    MINUTE_FIELDS,
    validate_snapshot,
)

# Sentinel meaning "remove this key entirely" so the field is missing (a
# violation for every required field).
_MISSING = object()

# --- Valid base-field strategies (produce a snapshot that fully validates) -----

_valid_id = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

# Years 2000–2099 keep %Y four digits on every platform (incl. Windows) so the
# formatted string is always a valid ISO 8601 'Z' timestamp.
_valid_timestamp = st.datetimes(
    min_value=_dt.datetime(2000, 1, 1),
    max_value=_dt.datetime(2099, 12, 31, 23, 59, 59),
).map(lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ"))

_valid_integer = st.integers(min_value=0, max_value=1_000_000)
_valid_minute = st.floats(
    min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False
)
_valid_confidence = st.floats(
    min_value=0, max_value=1, allow_nan=False, allow_infinity=False
)
_valid_slowest = st.none() | _valid_id

# --- Invalid injections (each member is guaranteed to violate the field rule) --

# Required identifier (station_id): missing, null, or a malformed/wrong-type value.
_invalid_required_id = st.one_of(
    st.just(_MISSING),
    st.none(),
    st.just(""),
    st.from_regex(r"[A-Z]{1,10}", fullmatch=True),  # uppercase not allowed
    st.just("a" * 65),  # too long
    st.just("has space"),  # disallowed char
    st.integers(),  # wrong type
)

# Optional identifier (slowest_lane_id): null is VALID, so only inject non-null
# malformed values — never _MISSING and never None.
_invalid_optional_id = st.one_of(
    st.just(""),
    st.from_regex(r"[A-Z]{1,10}", fullmatch=True),
    st.just("a" * 65),
    st.just("has space"),
    st.integers(),
)

_invalid_timestamp = st.one_of(
    st.just(_MISSING),
    st.none(),
    st.just("not a date"),
    st.just("2026-06-12T13:45:00"),  # naive: no offset / 'Z'
    st.just(""),
    st.integers(),
)

_invalid_integer = st.one_of(
    st.just(_MISSING),
    st.none(),
    st.integers(max_value=-1),  # below range
    st.integers(min_value=1_000_001),  # above range
    st.just(3.5),  # float, not int
    st.booleans(),  # bool is not an acceptable integer
    st.text(alphabet="abc", min_size=1, max_size=3),  # wrong type
)

_invalid_minute = st.one_of(
    st.just(_MISSING),
    st.none(),
    st.floats(max_value=-0.1, allow_nan=False, allow_infinity=False),  # below range
    st.floats(min_value=100_000.1, allow_nan=False, allow_infinity=False),  # above
    st.booleans(),
    st.text(alphabet="abc", min_size=1, max_size=3),
)

_invalid_confidence = st.one_of(
    st.just(_MISSING),
    st.none(),
    st.floats(max_value=-0.1, allow_nan=False, allow_infinity=False),  # below 0
    st.floats(min_value=1.0001, allow_nan=False, allow_infinity=False),  # above 1
    st.booleans(),
    st.text(alphabet="abc", min_size=1, max_size=3),
)


def _invalid_strategy_for(field: str) -> st.SearchStrategy:
    """Return the invalid-value strategy appropriate for ``field``."""
    if field == "station_id":
        return _invalid_required_id
    if field == "slowest_lane_id":
        return _invalid_optional_id
    if field == "timestamp":
        return _invalid_timestamp
    if field in INTEGER_FIELDS:
        return _invalid_integer
    if field in MINUTE_FIELDS:
        return _invalid_minute
    if field == "confidence_score":
        return _invalid_confidence
    raise AssertionError(f"unhandled field {field!r}")  # pragma: no cover


@st.composite
def _snapshot_with_violations(draw) -> tuple[dict, set[str]]:
    """Build a snapshot that violates a known, non-empty subset of fields.

    Returns the candidate snapshot dict and the exact set of fields expected in
    ``failing_fields``.
    """
    snapshot: dict = {
        "station_id": draw(_valid_id),
        "timestamp": draw(_valid_timestamp),
        "vehicles_in_queue": draw(_valid_integer),
        "vehicles_in_bay": draw(_valid_integer),
        "active_lanes": draw(_valid_integer),
        "throughput_per_hour": draw(_valid_integer),
        "average_queue_wait_minutes": draw(_valid_minute),
        "average_inspection_minutes": draw(_valid_minute),
        "estimated_public_wait_minutes": draw(_valid_minute),
        "confidence_score": draw(_valid_confidence),
        "slowest_lane_id": draw(_valid_slowest),
    }

    violated = draw(
        st.sets(st.sampled_from(GLOSSARY_FIELDS), min_size=1)
    )
    for field in violated:
        value = draw(_invalid_strategy_for(field))
        if value is _MISSING:
            snapshot.pop(field, None)
        else:
            snapshot[field] = value

    return snapshot, set(violated)


# Feature: station-stats-api, Property 4: Rejected snapshots name exactly the failing fields and store nothing
@settings(max_examples=200)
@given(case=_snapshot_with_violations())
def test_rejected_snapshot_names_exactly_failing_fields_and_stores_nothing(
    case: tuple[dict, set[str]],
) -> None:
    """For any parsable snapshot that violates one or more validation rules, the
    validator reports it invalid, names exactly the violating fields (no
    duplicates), and yields no cleaned payload (nothing to store).
    """
    snapshot, expected_failing = case

    result = validate_snapshot(snapshot)

    # Invalid, and nothing is produced for storage (the handler stores only the
    # cleaned payload, which is None here).
    assert result.is_valid is False
    assert result.cleaned is None

    # Names exactly the set of violating fields.
    assert set(result.failing_fields) == expected_failing

    # failing_fields lists each field once — no duplicates.
    assert len(result.failing_fields) == len(set(result.failing_fields))
