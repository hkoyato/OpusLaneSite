"""Property-based test for drain ordering in LaneSightClient.

Uses Hypothesis to verify that a publishing pass (drain) attempts submissions
in non-decreasing (ascending) timestamp order and that, when a retryable
failure occurs partway through, the remaining snapshots stay in the buffer in
ascending timestamp order for the next pass.

Also tests the full-success case: when the transport always succeeds (201),
all submissions are in ascending order and the buffer ends empty.

Validates: Requirements 8.5, 8.7
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.client import LaneSightClient, SnapshotTransport
from lanesight_client.models import ClientConfig, Snapshot
from station_stats_api.timestamps import to_utc_instant


@dataclass(frozen=True)
class _FakeResponse:
    """Minimal response object satisfying the SnapshotTransport protocol."""

    status_code: int


class _OrderTrackingTransport:
    """A fake transport that records submission order and fails at a given index.

    Args:
        fail_at_index: The 0-based index of the submission that should return
            503. If None, all submissions succeed with 201.
    """

    def __init__(self, fail_at_index: int | None = None) -> None:
        self._fail_at_index = fail_at_index
        self.submitted_timestamps: list[str] = []
        self._call_count = 0

    def post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.submitted_timestamps.append(json_body["timestamp"])
        current_index = self._call_count
        self._call_count += 1
        if self._fail_at_index is not None and current_index == self._fail_at_index:
            return _FakeResponse(status_code=503)
        return _FakeResponse(status_code=201)


# Strategy: generate 2-10 distinct timestamps for snapshots.
@st.composite
def snapshot_list_and_fail_index(draw: st.DrawFn) -> tuple[list[Snapshot], int]:
    """Generate 2-10 snapshots with distinct timestamps and a fail index.

    The fail index is in [0, len(snapshots)-1], representing the k-th oldest
    snapshot where the transport will return 503.
    """
    count = draw(st.integers(min_value=2, max_value=10))
    # Generate distinct second offsets so timestamps are unique.
    offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=5_000_000),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    base = datetime(2020, 1, 1, 0, 0, 0)
    snapshots = []
    for i, off in enumerate(offsets):
        moment = base + timedelta(seconds=off)
        ts = moment.isoformat(timespec="seconds") + "Z"
        station_id = "demo_station_01"
        snapshots.append(
            Snapshot(
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
        )
    # Fail index drawn from [0, count-1].
    fail_index = draw(st.integers(min_value=0, max_value=count - 1))
    return snapshots, fail_index


@st.composite
def snapshot_list_full_success(draw: st.DrawFn) -> list[Snapshot]:
    """Generate 2-10 snapshots with distinct timestamps for full-success case."""
    count = draw(st.integers(min_value=2, max_value=10))
    offsets = draw(
        st.lists(
            st.integers(min_value=0, max_value=5_000_000),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    base = datetime(2020, 1, 1, 0, 0, 0)
    snapshots = []
    for i, off in enumerate(offsets):
        moment = base + timedelta(seconds=off)
        ts = moment.isoformat(timespec="seconds") + "Z"
        station_id = "demo_station_01"
        snapshots.append(
            Snapshot(
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
        )
    return snapshots


def _make_client(
    transport: SnapshotTransport,
) -> tuple[LaneSightClient, PendingSnapshotBuffer, list[float]]:
    """Create a configured LaneSightClient with the given transport."""
    config = ClientConfig(
        api_base_url="https://api.example.com",
        client_credential="test-credential-key",
    )
    buffer = PendingSnapshotBuffer()
    retry_calls: list[float] = []

    def fake_retry_scheduler(delay: float, callback) -> None:
        retry_calls.append(delay)

    client = LaneSightClient(
        config=config,
        buffer=buffer,
        station_identifier="demo_station_01",
        transport=transport,
        retry_scheduler=fake_retry_scheduler,
    )
    return client, buffer, retry_calls


# Feature: station-stats-api, Property 13: Draining publishes in ascending timestamp order and preserves order on failure
@settings(max_examples=100, deadline=None)
@given(data=snapshot_list_and_fail_index())
def test_drain_ordering_failure_case(
    data: tuple[list[Snapshot], int],
) -> None:
    """For any set of buffered snapshots, when the transport fails (503) at the
    k-th oldest submission:

    1. Submissions up to (but not including) the failure point were in
       non-decreasing timestamp order.
    2. The submission at the failure point is also in non-decreasing order
       relative to those before it.
    3. The remaining snapshots are retained in the buffer in ascending
       timestamp order.
    4. A retry was scheduled.
    """
    # **Validates: Requirements 8.5, 8.7**
    snapshots, fail_index = data

    transport = _OrderTrackingTransport(fail_at_index=fail_index)
    client, buffer, retry_calls = _make_client(transport)

    # Manually add all snapshots to the buffer (in arbitrary order — the buffer
    # sorts them by ascending timestamp internally).
    for s in snapshots:
        buffer.add(s)

    # Trigger a drain pass.
    client.drain()

    # The transport should have been called (fail_index + 1) times: all
    # successful submissions before the failure, plus the failure itself.
    assert len(transport.submitted_timestamps) == fail_index + 1

    # Assert: all submitted timestamps are in non-decreasing UTC order.
    submitted_instants = [
        to_utc_instant(ts) for ts in transport.submitted_timestamps
    ]
    for i in range(len(submitted_instants) - 1):
        assert submitted_instants[i] <= submitted_instants[i + 1], (
            f"Submitted timestamps not in ascending order at index {i}: "
            f"{submitted_instants[i]} > {submitted_instants[i + 1]}"
        )

    # Assert: the buffer retains the remaining snapshots (those not successfully
    # published) in ascending timestamp order.
    remaining = list(buffer)
    remaining_instants = [to_utc_instant(s.timestamp) for s in remaining]
    for i in range(len(remaining_instants) - 1):
        assert remaining_instants[i] <= remaining_instants[i + 1], (
            f"Remaining buffer not in ascending order at index {i}: "
            f"{remaining_instants[i]} > {remaining_instants[i + 1]}"
        )

    # The number of remaining snapshots should be total - (successfully published).
    # Successfully published = fail_index (all before the failure).
    assert len(remaining) == len(snapshots) - fail_index

    # A retry was scheduled (Req 8.7: resume after the next backoff interval).
    assert len(retry_calls) == 1


# Feature: station-stats-api, Property 13: Draining publishes in ascending timestamp order and preserves order on failure
@settings(max_examples=100, deadline=None)
@given(snapshots=snapshot_list_full_success())
def test_drain_ordering_full_success(snapshots: list[Snapshot]) -> None:
    """For any set of buffered snapshots, when the transport always returns 201:

    1. All submissions are in non-decreasing (ascending) timestamp order.
    2. The buffer ends empty.
    """
    # **Validates: Requirements 8.5, 8.7**
    transport = _OrderTrackingTransport(fail_at_index=None)
    client, buffer, retry_calls = _make_client(transport)

    # Add all snapshots to the buffer.
    for s in snapshots:
        buffer.add(s)

    # Trigger a drain pass.
    client.drain()

    # All snapshots should have been submitted.
    assert len(transport.submitted_timestamps) == len(snapshots)

    # Assert: all submitted timestamps are in non-decreasing UTC order.
    submitted_instants = [
        to_utc_instant(ts) for ts in transport.submitted_timestamps
    ]
    for i in range(len(submitted_instants) - 1):
        assert submitted_instants[i] <= submitted_instants[i + 1], (
            f"Submitted timestamps not in ascending order at index {i}: "
            f"{submitted_instants[i]} > {submitted_instants[i + 1]}"
        )

    # Buffer should be fully drained.
    assert len(buffer) == 0

    # No retry should have been scheduled (all succeeded).
    assert len(retry_calls) == 0
