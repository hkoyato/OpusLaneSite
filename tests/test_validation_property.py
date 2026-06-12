"""Property-based test for Station_Metric_Snapshot validation acceptance.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for ``validate_snapshot``. The function under
test (``station_stats_api.validation.validate_snapshot``) is pure logic over an
already-parsed object, so this test runs headless and cheaply across many
generated inputs.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.8, 5.5
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.validation import (
    GLOSSARY_FIELDS,
    INTEGER_FIELDS,
    MINUTE_FIELDS,
    validate_snapshot,
)

# ---------------------------------------------------------------------------
# Strategies — generate WELL-FORMED snapshots and their field values
# ---------------------------------------------------------------------------

# Valid station_id / slowest_lane_id: 1-64 chars of [a-z0-9_-].
_valid_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

# Integer fields in [0, 1_000_000], mixing the boundary values 0, 1, 1000000
# with arbitrary in-range integers so Hypothesis exercises both edges and middle.
_valid_integer_strategy = st.one_of(
    st.sampled_from([0, 1, 1_000_000]),
    st.integers(min_value=0, max_value=1_000_000),
)

# Minute fields in [0, 100_000]: include the integer/float boundaries 0, 1.0,
# 100000 alongside arbitrary in-range numbers (ints and floats both valid).
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

# confidence_score in [0, 1]: include boundaries 0, 1, 1.0 and in-range floats.
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
        # 'Z' designator form (UTC).
        return base.isoformat() + "Z"
    # Explicit numeric offset form, e.g. -08:00 / +05:30 / +00:00.
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
# Property 3: Validation accepts exactly the well-formed snapshots
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 3: Validation accepts exactly the well-formed snapshots


@settings(max_examples=200)
@given(snapshot=_well_formed_snapshot())
def test_well_formed_snapshots_are_accepted(snapshot: dict) -> None:
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.8, 5.5**

    For any snapshot whose fields all satisfy the validation rules, validation
    succeeds, reports no failing fields, and returns a ``cleaned`` dict
    containing exactly the Glossary-defined fields with their submitted values.
    """
    result = validate_snapshot(snapshot)

    assert result.is_valid is True
    assert result.failing_fields == []
    assert result.cleaned is not None
    # cleaned contains exactly the Glossary fields, nothing more, nothing less.
    assert set(result.cleaned.keys()) == set(GLOSSARY_FIELDS)
    # Values are preserved exactly as submitted.
    for field in GLOSSARY_FIELDS:
        assert result.cleaned[field] == snapshot[field]


@settings(max_examples=100)
@given(
    snapshot=_well_formed_snapshot(),
    base_instant=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(timezone.utc),
    ),
    offset_minutes=st.integers(min_value=-12 * 60, max_value=14 * 60),
)
def test_same_instant_offset_and_z_both_validate(
    snapshot: dict, base_instant: datetime, offset_minutes: int
) -> None:
    """**Validates: Requirements 2.1**

    The same instant expressed as a ``Z`` (UTC) timestamp and as an equivalent
    explicit-offset timestamp are both well-formed, so a snapshot carrying
    either form validates successfully.
    """
    # 'Z' form of the instant (UTC).
    z_form = base_instant.isoformat().replace("+00:00", "") + "Z"

    # The same instant shifted into an arbitrary offset zone — a different
    # string denoting the same moment.
    offset = timezone(timedelta(minutes=offset_minutes))
    offset_form = base_instant.astimezone(offset).isoformat()

    z_snapshot = {**snapshot, "timestamp": z_form}
    offset_snapshot = {**snapshot, "timestamp": offset_form}

    assert validate_snapshot(z_snapshot).is_valid is True
    assert validate_snapshot(offset_snapshot).is_valid is True


@settings(max_examples=200)
@given(
    snapshot=_well_formed_snapshot(),
    field=st.sampled_from(GLOSSARY_FIELDS),
)
def test_mutating_one_field_invalid_is_rejected(snapshot: dict, field: str) -> None:
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.8, 5.5**

    The biconditional direction: corrupting a single field of an otherwise
    well-formed snapshot with an out-of-domain value causes validation to fail
    and names that field among the failing fields. ``slowest_lane_id`` is the
    only field that accepts ``null``, but an invalid non-null string still fails.
    """
    mutated = dict(snapshot)
    if field in ("station_id", "slowest_lane_id"):
        # An invalid identifier: uppercase is outside [a-z0-9_-].
        mutated[field] = "INVALID ID!"
    elif field == "timestamp":
        # A naive timestamp lacks the required offset/'Z'.
        mutated[field] = "2026-06-12T13:45:00"
    elif field in INTEGER_FIELDS:
        # Out of range for an integer field.
        mutated[field] = 1_000_001
    elif field in MINUTE_FIELDS:
        mutated[field] = 100_000.5
    else:  # confidence_score
        mutated[field] = 1.5

    result = validate_snapshot(mutated)

    assert result.is_valid is False
    assert field in result.failing_fields
    assert result.cleaned is None
