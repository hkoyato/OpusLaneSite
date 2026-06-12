"""Unit tests for malformed-JSON and oversize request bodies.

These are concrete example tests (not property tests) for the Snapshot (POST)
handler ``station_stats_api.snapshot_handler.handle_snapshot``. They cover the
two body-level rejection paths from design.md "Server-side error mapping":

- An unparseable request body -> HTTP 400 (malformed JSON), nothing stored.
- A request body larger than 16 kilobytes -> HTTP 413 identifying the request
  as exceeding the maximum allowed body size, nothing stored.

A body at or just under the 16KB limit is *not* rejected for size; it follows
the normal validate/store path.

Validates: Requirements 2.5, 1.6
"""

from __future__ import annotations

import json

import pytest

from station_stats_api.http_result import (
    HTTP_BAD_REQUEST,
    HTTP_CREATED,
    HTTP_PAYLOAD_TOO_LARGE,
)
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.snapshot_handler import MAX_BODY_BYTES, handle_snapshot


def _valid_snapshot() -> dict:
    """Return a minimal snapshot whose every field satisfies Requirement 2."""
    return {
        "station_id": "demo_station_01",
        "timestamp": "2026-06-12T13:45:00Z",
        "vehicles_in_queue": 9,
        "vehicles_in_bay": 3,
        "active_lanes": 3,
        "average_queue_wait_minutes": 14.2,
        "average_inspection_minutes": 6.4,
        "estimated_public_wait_minutes": 18,
        "throughput_per_hour": 28,
        "slowest_lane_id": "lane_2",
        "confidence_score": 0.82,
    }


def _store_is_empty(store: InMemoryStatisticsStore) -> bool:
    """True when no snapshot is stored for any station."""
    return store.list_index() == []


# ---------------------------------------------------------------------------
# Malformed JSON -> 400, nothing stored (Req 2.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_body",
    [
        b"{not json",
        b"",
        b"\xff\xfe garbage",
        b"[1, 2,",
        b"null trailing",
        b"{\"station_id\": }",
    ],
)
def test_unparseable_body_returns_400_and_stores_nothing(raw_body: bytes) -> None:
    """**Validates: Requirements 2.5**

    A body that cannot be parsed as JSON (including a non-UTF-8 body and an
    empty body) yields HTTP 400 with a malformed-JSON message, and no snapshot
    is stored.
    """
    store = InMemoryStatisticsStore()

    result = handle_snapshot(raw_body, store)

    assert result.status_code == HTTP_BAD_REQUEST
    assert isinstance(result.body, dict)
    assert "malformed" in result.body["error"].lower()
    assert _store_is_empty(store)


# ---------------------------------------------------------------------------
# Oversize body -> 413, nothing stored (Req 1.6)
# ---------------------------------------------------------------------------


def test_body_over_16kb_returns_413_with_max_body_message_and_stores_nothing() -> None:
    """**Validates: Requirements 1.6**

    A POST whose body exceeds 16 kilobytes is rejected with HTTP 413, the
    response body identifies the request as exceeding the maximum allowed body
    size, and nothing is stored — even though the underlying JSON is a valid
    snapshot once an oversize padding field is added.
    """
    store = InMemoryStatisticsStore()
    snapshot = _valid_snapshot()
    # Pad with an extra valid string field large enough to push the serialized
    # body well past 16KB. Extra keys would normally be stripped, but the size
    # check happens first, so this never reaches validation/storage.
    snapshot["_pad"] = "x" * (MAX_BODY_BYTES + 1024)
    body = json.dumps(snapshot).encode()
    assert len(body) > MAX_BODY_BYTES

    result = handle_snapshot(body, store)

    assert result.status_code == HTTP_PAYLOAD_TOO_LARGE
    assert isinstance(result.body, dict)
    message = result.body["error"].lower()
    assert "maximum allowed body size" in message
    assert _store_is_empty(store)


def test_body_just_over_limit_returns_413() -> None:
    """**Validates: Requirements 1.6**

    A body exactly one byte over the limit is rejected for size.
    """
    store = InMemoryStatisticsStore()
    raw_body = b"x" * (MAX_BODY_BYTES + 1)

    result = handle_snapshot(raw_body, store)

    assert result.status_code == HTTP_PAYLOAD_TOO_LARGE
    assert _store_is_empty(store)


def test_body_at_limit_is_not_rejected_for_size() -> None:
    """**Validates: Requirements 1.6**

    A body exactly at the 16KB limit is not rejected for size. It is not a 413;
    it proceeds to the normal parse/validate path (here a malformed 400).
    """
    store = InMemoryStatisticsStore()
    raw_body = b"x" * MAX_BODY_BYTES  # at limit, unparseable JSON

    result = handle_snapshot(raw_body, store)

    assert result.status_code != HTTP_PAYLOAD_TOO_LARGE
    # Unparseable content at the limit falls through to the malformed-JSON path.
    assert result.status_code == HTTP_BAD_REQUEST
    assert _store_is_empty(store)


def test_valid_body_just_under_limit_is_stored() -> None:
    """**Validates: Requirements 1.6**

    A valid snapshot whose serialized size is just under 16KB is accepted and
    stored — the size check does not reject legitimate near-limit payloads. The
    snapshot is padded with an extra key (stripped on storage) so its wire size
    approaches but stays below the limit.
    """
    store = InMemoryStatisticsStore()
    snapshot = _valid_snapshot()
    base_size = len(json.dumps(snapshot).encode())
    # Pad so the serialized body lands a small margin under the limit.
    pad_len = MAX_BODY_BYTES - base_size - len(',"_pad":""') - 16
    snapshot["_pad"] = "x" * pad_len
    body = json.dumps(snapshot).encode()
    assert len(body) <= MAX_BODY_BYTES

    result = handle_snapshot(body, store)

    # Accepted and stored (extra _pad key stripped); not a size rejection.
    assert result.status_code == HTTP_CREATED
    assert not _store_is_empty(store)
    assert store.get(snapshot["station_id"]) is not None
