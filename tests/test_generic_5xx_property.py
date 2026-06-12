"""Property-based test for generic 5xx response bodies.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the Snapshot (POST) handler
(``station_stats_api.snapshot_handler.handle_snapshot``). When the
``Statistics_Store`` raises a storage fault, the handler maps it to a ``5xx``
(``503``) response whose body is generic — it must never leak internal stack
traces, internal error codes, or implementation details that the failing store
carried in its exception message (Requirement 10.4, design "Generic 5xx
bodies").

The handler and the in-memory store seam are pure logic over already-parsed
data, so this test runs headless and cheaply across many generated inputs and
injected fault types.

Validates: Requirements 10.4
"""

from __future__ import annotations

import json
from datetime import datetime

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.http_result import HTTP_SERVICE_UNAVAILABLE
from station_stats_api.snapshot_handler import handle_snapshot
from station_stats_api.validation import INTEGER_FIELDS, MINUTE_FIELDS

# ---------------------------------------------------------------------------
# Valid-snapshot strategies — mirror test_snapshot_accept_property.py so a valid
# snapshot always reaches the storage step (the only path that can raise 5xx).
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


# ---------------------------------------------------------------------------
# Sensitive / internal-looking exception payloads
# ---------------------------------------------------------------------------
# Hypothesis-generated text that mimics the kind of internal detail a real
# storage backend might leak in an exception message: stack-trace fragments,
# internal error codes, table names, and secrets. The property asserts NONE of
# this ever reaches the response body.

# A non-trivial chunk of arbitrary text so the substring-absence check is
# meaningful (1+ chars, excludes empty which is trivially "present").
_sensitive_text = st.text(min_size=4, max_size=120)

# Internal-code-like tokens (e.g. "DDB-5521", "ERR_0xDEADBEEF").
_internal_code = st.from_regex(r"(ERR|DDB|SEC|INT)[-_][0-9A-Fx]{3,10}", fullmatch=True)

# Fake stack-trace text that includes the "Traceback" marker we explicitly bar.
_stack_trace_text = st.from_regex(
    r'Traceback \(most recent call last\):\n  File "/srv/[a-z/]+\.py", line [0-9]{1,4}',
    fullmatch=True,
)

# Table-name / secret-like tokens.
_table_name = st.from_regex(r"StationStatistics_(prod|stg)_[a-z0-9]{4,12}", fullmatch=True)
_secret_text = st.from_regex(r"(AKIA|secret_|token_)[A-Za-z0-9]{8,24}", fullmatch=True)


class _FakeClientError(Exception):
    """A botocore ``ClientError``-like exception carrying a sensitive message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        # Mimic botocore's nested ``response`` structure that often leaks codes.
        self.response = {
            "Error": {"Code": "InternalServerError", "Message": message},
            "ResponseMetadata": {"RequestId": "req-DEADBEEF-internal"},
        }


@st.composite
def _faulting_store(draw: st.DrawFn) -> tuple[object, str]:
    """Build a store whose ``put_if_newer`` raises with an injected message.

    Returns a ``(store, injected_message)`` pair. ``injected_message`` is the
    full sensitive string the exception carries; the property asserts it never
    appears in the serialized response body.
    """
    # Compose a sensitive message from several internal-looking fragments so a
    # single body must avoid all of them.
    parts = [
        draw(_sensitive_text),
        draw(_internal_code),
        draw(_stack_trace_text),
        draw(_table_name),
        draw(_secret_text),
    ]
    message = " | ".join(parts)

    # Rotate across several exception types to prove they all map to a generic
    # 5xx body regardless of class (RuntimeError, ValueError, ClientError-like).
    exc_factory = draw(
        st.sampled_from(
            [
                lambda m: RuntimeError(m),
                lambda m: ValueError(m),
                lambda m: KeyError(m),
                _FakeClientError,
            ]
        )
    )
    exc = exc_factory(message)

    class _FaultingStore:
        def put_if_newer(self, snapshot: dict):
            raise exc

        def get(self, station_id: str):
            return None

        def list_index(self):
            return []

    return _FaultingStore(), message


# ---------------------------------------------------------------------------
# Property 20: 5xx responses are generic
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 20: 5xx responses are generic

# A list-form generic phrasing the body is expected to use, lower-cased for a
# case-insensitive containment check.
_GENERIC_PHRASE = "could not be completed"


@settings(max_examples=200)
@given(snapshot=_well_formed_snapshot(), store_and_message=_faulting_store())
def test_5xx_responses_are_generic(
    snapshot: dict, store_and_message: tuple[object, str]
) -> None:
    """**Validates: Requirements 10.4**

    For any request that results in a 5xx response, the response body contains a
    generic "could not be completed" message and contains no internal stack
    traces, internal error codes, or implementation details.

    A valid snapshot is submitted to a store that always raises a storage fault
    whose exception message carries sensitive/internal-looking text (fake stack
    traces, internal codes, table names, secrets). The handler must map every
    such fault to a 503 whose serialized body leaks none of that text.
    """
    store, injected_message = store_and_message
    body = json.dumps(snapshot).encode()

    result = handle_snapshot(body, store)

    # The storage fault maps to a 5xx response (503 specifically) (Req 10.2/10.4).
    assert 500 <= result.status_code < 600
    assert result.status_code == HTTP_SERVICE_UNAVAILABLE

    # The body must be JSON-serializable; serialize it to inspect everything the
    # client would actually receive.
    serialized = json.dumps(result.body)
    serialized_lower = serialized.lower()

    # It carries a generic "could not be completed"-style message (Req 10.4).
    assert _GENERIC_PHRASE in serialized_lower

    # It leaks none of the injected internal/exception text (Req 10.4). Check the
    # whole message and each non-trivial fragment of it. Skip any fragment that
    # is itself a substring of the fixed generic body (free-text generators can
    # coincidentally produce words like "the request" that legitimately appear
    # in the safe message), so the check only flags genuinely foreign text.
    assert injected_message not in serialized
    for fragment in injected_message.split(" | "):
        if len(fragment) >= 4 and fragment not in serialized:
            continue
        if len(fragment) >= 4:
            # Fragment IS present in the body — only acceptable if it is part of
            # the fixed generic message rather than leaked internal detail.
            assert fragment in _GENERIC_PHRASE or fragment in '{"error": "the request could not be completed"}'

    # No stack-trace marker and no obvious internal-detail markers leak.
    assert "Traceback" not in serialized
    assert "most recent call last" not in serialized
    assert "RequestId" not in serialized
    assert "InternalServerError" not in serialized
    assert ".py" not in serialized
