"""Property-based test for station-id stamping in LaneSightClient.

Verifies that when a snapshot is produced, the LaneSight_Client stamps its
station_id with the active Station_Identifier at production time, and submits
the snapshot to the matching URL path via a Submission_Attempt.

Validates: Requirements 7.1, 7.2, 7.7
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.client import (
    CREDENTIAL_HEADER,
    SNAPSHOT_PATH_TEMPLATE,
    LaneSightClient,
    SnapshotTransport,
)
from lanesight_client.models import ClientConfig, Snapshot


# --- Strategies ---------------------------------------------------------------

# Valid station identifiers: 1-64 chars from [a-z0-9_-]
_station_id_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)


@st.composite
def station_id_pair(draw: st.DrawFn) -> tuple[str, str]:
    """Generate two distinct valid station identifiers."""
    active = draw(_station_id_strategy)
    original = draw(_station_id_strategy.filter(lambda s: s != active))
    return active, original


# --- Recording transport ------------------------------------------------------


@dataclass(frozen=True)
class _FakeResponse:
    """Minimal response object satisfying the SnapshotTransport protocol."""

    status_code: int


class _RecordingTransport:
    """A fake SnapshotTransport that records all submissions and returns 201."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "url": url,
                "json_body": json_body,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse(status_code=201)


# Feature: station-stats-api, Property 16: Submitted snapshots carry the active station identifier
@settings(max_examples=100, deadline=None)
@given(data=station_id_pair())
def test_submitted_snapshots_carry_the_active_station_identifier(
    data: tuple[str, str],
) -> None:
    """For any produced snapshot with a DIFFERENT station_id, the client stamps
    the submitted snapshot's station_id with the active Station_Identifier and
    submits to the matching URL path.

    Asserts:
    - The submitted json_body["station_id"] == the active station_identifier.
    - The URL path includes the active station_identifier.
    - A submission attempt was made (Req 7.7).
    """
    # **Validates: Requirements 7.1, 7.2, 7.7**
    active_station_id, original_station_id = data

    # Create a snapshot with a DIFFERENT station_id than the active one.
    offset_seconds = 1_000_000
    base = datetime(2024, 1, 1, 0, 0, 0)
    moment = base + timedelta(seconds=offset_seconds)
    ts = moment.isoformat(timespec="seconds") + "Z"

    snapshot = Snapshot(
        station_id=original_station_id,
        timestamp=ts,
        payload={
            "station_id": original_station_id,
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

    # Set up a configured client with a recording transport.
    config = ClientConfig(
        api_base_url="https://api.example.com",
        client_credential="test-credential-key",
    )
    buffer = PendingSnapshotBuffer()
    transport = _RecordingTransport()

    # No-op retry scheduler (won't be needed since transport returns 201).
    def noop_retry_scheduler(delay: float, callback) -> None:
        pass

    client = LaneSightClient(
        config=config,
        buffer=buffer,
        station_identifier=active_station_id,
        transport=transport,
        retry_scheduler=noop_retry_scheduler,
    )

    # Produce the snapshot — this enqueues, stamps, and attempts to drain.
    client.on_snapshot_produced(snapshot)

    # Assert: a submission attempt was made (Req 7.7).
    assert len(transport.calls) == 1, (
        f"Expected exactly 1 submission attempt, got {len(transport.calls)}"
    )

    call = transport.calls[0]

    # Assert: the submitted json_body["station_id"] == the active station_identifier
    # (not the snapshot's original station_id). This validates Req 7.2.
    assert call["json_body"]["station_id"] == active_station_id, (
        f"Expected submitted station_id to be the active '{active_station_id}', "
        f"got '{call['json_body']['station_id']}'"
    )

    # Assert: the URL path includes the active station_identifier.
    expected_path = SNAPSHOT_PATH_TEMPLATE.format(station_id=active_station_id)
    assert expected_path in call["url"], (
        f"Expected URL to contain '{expected_path}', got '{call['url']}'"
    )
