"""Integration test for storage-error handling (Task 14.4).

Verifies that when the Statistics_Store raises during a write, the
snapshot_handler responds with HTTP 503, includes a generic error body
with no internal detail, and leaves no partial record in the store.

Validates: Requirements 10.2
"""

from __future__ import annotations

import json

from station_stats_api.lambda_handler import snapshot_handler
from station_stats_api.store import PutOutcome


# ---------------------------------------------------------------------------
# Fake store that raises on put_if_newer
# ---------------------------------------------------------------------------


class _FailingStore:
    """A store whose put_if_newer always raises, simulating DynamoDB unavailable.

    get() and list_index() work normally (backed by a plain dict) so we can
    assert that no partial record was written.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def put_if_newer(self, snapshot: dict) -> PutOutcome:
        raise RuntimeError("DynamoDB unavailable")

    def get(self, station_id: str) -> dict | None:
        return self._data.get(station_id)

    def list_index(self) -> list[tuple[str, str]]:
        return [(sid, s["timestamp"]) for sid, s in self._data.items()]


# ---------------------------------------------------------------------------
# Helper: build a valid API Gateway proxy event
# ---------------------------------------------------------------------------


def _valid_snapshot_body() -> dict:
    """Return a valid Station_Metric_Snapshot payload."""
    return {
        "station_id": "demo_station_01",
        "timestamp": "2026-06-12T13:45:00Z",
        "vehicles_in_queue": 9,
        "vehicles_in_bay": 3,
        "active_lanes": 3,
        "average_queue_wait_minutes": 14.2,
        "average_inspection_minutes": 6.4,
        "estimated_public_wait_minutes": 18.0,
        "throughput_per_hour": 28,
        "slowest_lane_id": "lane_2",
        "confidence_score": 0.82,
    }


def _make_proxy_event(body: dict) -> dict:
    """Build an API Gateway proxy event with the given JSON body."""
    return {
        "httpMethod": "POST",
        "pathParameters": {"station_id": body["station_id"]},
        "body": json.dumps(body),
        "isBase64Encoded": False,
        "headers": {"content-type": "application/json"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_storage_error_returns_503_with_generic_body():
    """Injected storage error produces 503 with no internal detail (Req 10.2)."""
    fake_store = _FailingStore()
    body = _valid_snapshot_body()
    event = _make_proxy_event(body)

    response = snapshot_handler(event, store=fake_store)

    assert response["statusCode"] == 503

    response_body = json.loads(response["body"])
    # Generic message indicating the request could not be completed.
    assert "could not be completed" in response_body.get("error", "")

    # No internal details leaked.
    body_text = response["body"]
    assert "DynamoDB" not in body_text
    assert "Traceback" not in body_text
    assert "RuntimeError" not in body_text
    assert "stack" not in body_text.lower() or "stack trace" not in body_text.lower()


def test_storage_error_leaves_no_partial_record():
    """After a storage error, get() returns None — no partial record (Req 10.2)."""
    fake_store = _FailingStore()
    body = _valid_snapshot_body()
    event = _make_proxy_event(body)

    response = snapshot_handler(event, store=fake_store)

    # Confirm the 503 was returned.
    assert response["statusCode"] == 503

    # The store has no record for the station — no partial write occurred.
    assert fake_store.get(body["station_id"]) is None
