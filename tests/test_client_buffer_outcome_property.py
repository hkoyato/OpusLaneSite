"""Property-based test for per-response buffer handling in LaneSightClient.

Uses Hypothesis to verify that the LaneSight_Client correctly handles each
SubmitOutcome — removing snapshots on PUBLISHED/DUPLICATE, discarding on
DISCARDED, and retaining for retry on RETRY — and that the notification state
matches the outcome.

Validates: Requirements 7.3, 7.4, 8.1, 8.6
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.client import LaneSightClient, SnapshotTransport
from lanesight_client.models import ClientConfig, Snapshot, SubmitOutcome
from lanesight_client.notification import NotificationCategory

# HTTP status codes that map to each SubmitOutcome.
_OUTCOME_STATUS_MAP: dict[SubmitOutcome, list[int]] = {
    SubmitOutcome.PUBLISHED: [201],
    SubmitOutcome.DUPLICATE: [200],
    SubmitOutcome.DISCARDED: [400, 422],
    SubmitOutcome.RETRY: [503],
}


@dataclass(frozen=True)
class _FakeResponse:
    """Minimal response object satisfying the SnapshotTransport protocol."""

    status_code: int


class _FakeTransport:
    """A fake SnapshotTransport that returns a predetermined HTTP status."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    def post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        return _FakeResponse(status_code=self._status_code)


@st.composite
def snapshot_and_outcome(draw: st.DrawFn) -> tuple[Snapshot, SubmitOutcome, int]:
    """Generate a snapshot, a SubmitOutcome, and the corresponding HTTP status."""
    # Generate a valid ISO 8601 timestamp.
    offset_seconds = draw(st.integers(min_value=0, max_value=5_000_000))
    base = datetime(2020, 1, 1, 0, 0, 0)
    moment = base + timedelta(seconds=offset_seconds)
    ts = moment.isoformat(timespec="seconds") + "Z"

    station_id = draw(st.from_regex(r"[a-z0-9_-]{1,16}", fullmatch=True))

    snapshot = Snapshot(
        station_id=station_id,
        timestamp=ts,
        payload={
            "station_id": station_id,
            "timestamp": ts,
            "vehicles_in_queue": 5,
            "vehicles_in_bay": 2,
            "active_lanes": 3,
            "average_queue_wait_minutes": 10.0,
            "average_inspection_minutes": 5.0,
            "estimated_public_wait_minutes": 15.0,
            "throughput_per_hour": 20,
            "slowest_lane_id": None,
            "confidence_score": 0.9,
        },
    )

    outcome = draw(st.sampled_from(list(SubmitOutcome)))
    # Pick an HTTP status that maps to this outcome.
    http_status = draw(st.sampled_from(_OUTCOME_STATUS_MAP[outcome]))

    return snapshot, outcome, http_status


# Feature: station-stats-api, Property 11: Buffer outcome handling is correct per response
@settings(max_examples=100, deadline=None)
@given(data=snapshot_and_outcome())
def test_buffer_outcome_handling_is_correct_per_response(
    data: tuple[Snapshot, SubmitOutcome, int],
) -> None:
    """For any snapshot and SubmitOutcome, assert:

    - PUBLISHED/DUPLICATE -> buffer is empty (snapshot removed).
    - DISCARDED -> buffer is empty (snapshot discarded).
    - RETRY -> buffer still contains the snapshot (retained for retry).

    Also assert notification state matches:
    - SUCCESS for PUBLISHED/DUPLICATE.
    - OUTAGE for RETRY (503).
    """
    # **Validates: Requirements 7.3, 7.4, 8.1, 8.6**
    snapshot, outcome, http_status = data

    # Set up a configured client with a fake transport returning the given status.
    config = ClientConfig(
        api_base_url="https://api.example.com",
        client_credential="test-credential-key",
    )
    buffer = PendingSnapshotBuffer()
    transport = _FakeTransport(status_code=http_status)

    # Collect retry scheduler calls to prevent actual timer creation.
    retry_calls: list[float] = []

    def fake_retry_scheduler(delay: float, callback) -> None:
        retry_calls.append(delay)

    # Track notification states.
    notifications: list = []

    client = LaneSightClient(
        config=config,
        buffer=buffer,
        station_identifier=snapshot.station_id,
        transport=transport,
        notification_sink=notifications.append,
        retry_scheduler=fake_retry_scheduler,
    )

    # Produce the snapshot — this enqueues, stamps, and attempts to drain.
    client.on_snapshot_produced(snapshot)

    if outcome in (SubmitOutcome.PUBLISHED, SubmitOutcome.DUPLICATE):
        # Req 7.3, 8.6: snapshot successfully published -> removed from buffer.
        assert len(buffer) == 0, (
            f"Expected buffer empty after {outcome.name}, got {len(buffer)}"
        )
        # Notification should indicate SUCCESS (publishing resumed / active).
        assert client.notification_state is not None
        assert client.notification_state.category == NotificationCategory.NONE
        assert client.notification_state.visible is False

    elif outcome is SubmitOutcome.DISCARDED:
        # Req 7.4: terminal rejection -> snapshot discarded from buffer.
        assert len(buffer) == 0, (
            f"Expected buffer empty after DISCARDED, got {len(buffer)}"
        )

    elif outcome is SubmitOutcome.RETRY:
        # Req 8.1: retryable failure -> snapshot retained in buffer.
        assert len(buffer) == 1, (
            f"Expected buffer to retain 1 snapshot on RETRY, got {len(buffer)}"
        )
        # The retained snapshot should be the one we produced.
        retained = buffer.peek_oldest()
        assert retained is not None
        assert retained.timestamp == snapshot.timestamp
        # Notification should indicate OUTAGE (503 -> outage category).
        assert client.notification_state is not None
        assert client.notification_state.category == NotificationCategory.OUTAGE
        assert client.notification_state.visible is True
        # A retry should have been scheduled.
        assert len(retry_calls) == 1
