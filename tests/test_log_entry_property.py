"""Property-based test for the Station_Stats_API log-entry builder.

Uses Hypothesis to verify that every handled Snapshot_Endpoint request produces
exactly one complete log entry: it records the Station_Identifier (or an explicit
``<absent>`` / ``<unparseable>`` indicator), the resulting HTTP status code, the
request timestamp as an ISO 8601 value, and — only for a rejected request — a
category describing the rejection reason. The unit under test,
``station_stats_api.logging_support.build_log_entry`` (plus the guarded
``emit_log``), is pure logic with no AWS calls, so the test runs cheaply across
many generated inputs.

Validates: Requirements 10.1
"""

from __future__ import annotations

from datetime import datetime, timezone

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.logging_support import (
    STATION_ID_ABSENT,
    STATION_ID_UNPARSEABLE,
    build_log_entry,
    emit_log,
)

# The set of real HTTP statuses a handled Snapshot_Endpoint request can produce.
# Mix of success (<400) and rejection (>=400) statuses (design.md error map).
_HTTP_STATUSES = [200, 201, 400, 401, 403, 404, 405, 413, 422, 500, 503]

# Rejection categories recorded for rejected requests (log-only vocabulary).
_REJECTION_CATEGORIES = [
    "malformed_json",
    "validation_failed",
    "payload_too_large",
    "unauthenticated",
    "forbidden",
    "method_not_allowed",
    "malformed_station_id",
    "not_found",
    "storage_error",
    "internal_error",
]

# --- station_id generators across the three Requirement 10.1 cases -------------

#: Valid identifiers: 1–64 chars of [a-z0-9_-].
_valid_station_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=64,
)

#: "Absent": no identifier was present on the request.
_absent_station_ids = st.sampled_from([None, ""])

#: Malformed / unparseable: present but not a well-formed identifier (uppercase,
#: spaces, punctuation, unicode, or longer than 64 chars).
_unparseable_station_ids = st.one_of(
    st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=10),
    st.text(alphabet=" !@#$%^&*().", min_size=1, max_size=10),
    st.just("has space"),
    st.just("Station_01"),
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
        min_size=65,
        max_size=120,
    ),
)

# A real ISO 8601 timestamp string with an explicit UTC offset or 'Z'.
_iso_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


def _assert_one_complete_entry(
    *,
    station_id: object,
    http_status: int,
    request_timestamp: str,
    rejection_category: str | None,
) -> None:
    """Build + emit one entry and assert it is a single, complete log record."""
    # A counting sink proves "exactly one entry per request" — emit_log invokes
    # the sink exactly once per handled request.
    emitted: list[dict] = []

    entry = build_log_entry(
        station_id=station_id,
        http_status=http_status,
        request_timestamp=request_timestamp,
        rejection_category=rejection_category,
    )

    assert emit_log(entry, sink=emitted.append) is True
    assert len(emitted) == 1  # exactly one entry per request (Req 10.1)

    # The entry is a single dict carrying exactly the required keys.
    assert isinstance(entry, dict)
    required_keys = {"station_id", "http_status", "request_timestamp"}
    if http_status >= 400:
        required_keys = required_keys | {"rejection_category"}
    assert set(entry.keys()) == required_keys

    # http_status is recorded exactly as the resulting status.
    assert entry["http_status"] == http_status

    # request_timestamp is a non-empty string that parses as ISO 8601.
    assert isinstance(entry["request_timestamp"], str)
    assert entry["request_timestamp"] != ""
    parsed = datetime.fromisoformat(entry["request_timestamp"])
    assert isinstance(parsed, datetime)

    # rejection_category present iff the request was rejected (status >= 400).
    if http_status >= 400:
        assert "rejection_category" in entry
        assert entry["rejection_category"] is not None
    else:
        assert "rejection_category" not in entry

    # station_id resolves to the correct indicator for each of the three cases.
    if station_id is None or station_id == "":
        assert entry["station_id"] == STATION_ID_ABSENT
    else:
        assert entry["station_id"] in (station_id, STATION_ID_UNPARSEABLE)


# Feature: station-stats-api, Property 19: Every handled request produces one complete log entry
@settings(max_examples=200)
@given(
    station_id=st.one_of(
        _valid_station_ids, _absent_station_ids, _unparseable_station_ids
    ),
    http_status=st.sampled_from(_HTTP_STATUSES),
    request_timestamp=_iso_timestamps,
    rejection_category=st.one_of(st.none(), st.sampled_from(_REJECTION_CATEGORIES)),
)
def test_every_handled_request_produces_one_complete_log_entry(
    station_id: object,
    http_status: int,
    request_timestamp: str,
    rejection_category: str | None,
) -> None:
    """For any handled request, build_log_entry produces exactly one complete
    log entry recording station_id (or an explicit indicator), the HTTP status,
    an ISO 8601 request timestamp, and — for rejected requests — a category.
    """
    _assert_one_complete_entry(
        station_id=station_id,
        http_status=http_status,
        request_timestamp=request_timestamp,
        rejection_category=rejection_category,
    )


# Feature: station-stats-api, Property 19: Every handled request produces one complete log entry
@settings(max_examples=100)
@given(
    station_id=_valid_station_ids,
    http_status=st.sampled_from([s for s in _HTTP_STATUSES if s >= 400]),
)
def test_valid_station_id_is_recorded_literally_for_rejections(
    station_id: str, http_status: int
) -> None:
    """A well-formed Station_Identifier is recorded literally, and a rejected
    request always carries a rejection category (defaulting when unspecified).
    """
    entry = build_log_entry(
        station_id=station_id,
        http_status=http_status,
        request_timestamp="2026-06-12T13:45:00Z",
    )

    assert entry["station_id"] == station_id
    assert entry["rejection_category"] is not None
