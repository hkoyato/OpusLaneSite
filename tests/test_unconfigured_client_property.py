"""Property-based test for unconfigured-client behavior in LaneSightClient.

Uses Hypothesis to verify that when either API_Base_URL or Client_Credential is
unconfigured (None, empty strings, or both missing), the LaneSight_Client makes
no submission attempt, removes the snapshot from the Pending_Snapshot_Buffer,
and the notification state has category NOT_CONFIGURED with visible=True.

Validates: Requirements 7.6
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.client import LaneSightClient, SnapshotTransport
from lanesight_client.models import ClientConfig, Snapshot
from lanesight_client.notification import NotificationCategory, NotificationState


@dataclass(frozen=True)
class _FakeResponse:
    """Minimal response object satisfying the SnapshotTransport protocol."""

    status_code: int


class _RecordingTransport:
    """A recording SnapshotTransport that tracks all calls made."""

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
            {"url": url, "json_body": json_body, "headers": headers, "timeout": timeout}
        )
        return _FakeResponse(status_code=201)


# Strategy for unconfigured ClientConfig variants: api_base_url=None,
# credential=None, both None, empty strings.
@st.composite
def unconfigured_config(draw: st.DrawFn) -> ClientConfig:
    """Generate ClientConfig variants where the client is NOT configured.

    A client is unconfigured when either api_base_url or client_credential
    is falsy (None or empty string). We generate all such combinations.
    """
    variant = draw(st.sampled_from([
        "api_url_none",
        "credential_none",
        "both_none",
        "api_url_empty",
        "credential_empty",
        "both_empty",
        "api_url_none_credential_empty",
        "api_url_empty_credential_none",
    ]))

    if variant == "api_url_none":
        return ClientConfig(api_base_url=None, client_credential="valid-key-123")
    elif variant == "credential_none":
        return ClientConfig(api_base_url="https://api.example.com", client_credential=None)
    elif variant == "both_none":
        return ClientConfig(api_base_url=None, client_credential=None)
    elif variant == "api_url_empty":
        return ClientConfig(api_base_url="", client_credential="valid-key-123")
    elif variant == "credential_empty":
        return ClientConfig(api_base_url="https://api.example.com", client_credential="")
    elif variant == "both_empty":
        return ClientConfig(api_base_url="", client_credential="")
    elif variant == "api_url_none_credential_empty":
        return ClientConfig(api_base_url=None, client_credential="")
    else:  # api_url_empty_credential_none
        return ClientConfig(api_base_url="", client_credential=None)


@st.composite
def arbitrary_snapshot(draw: st.DrawFn) -> Snapshot:
    """Generate an arbitrary valid snapshot for submission."""
    offset_seconds = draw(st.integers(min_value=0, max_value=5_000_000))
    base = datetime(2020, 1, 1, 0, 0, 0)
    moment = base + timedelta(seconds=offset_seconds)
    ts = moment.isoformat(timespec="seconds") + "Z"

    station_id = draw(st.from_regex(r"[a-z0-9_-]{1,16}", fullmatch=True))

    return Snapshot(
        station_id=station_id,
        timestamp=ts,
        payload={
            "station_id": station_id,
            "timestamp": ts,
            "vehicles_in_queue": draw(st.integers(min_value=0, max_value=100)),
            "vehicles_in_bay": draw(st.integers(min_value=0, max_value=20)),
            "active_lanes": draw(st.integers(min_value=1, max_value=10)),
            "average_queue_wait_minutes": draw(st.floats(min_value=0, max_value=60)),
            "average_inspection_minutes": draw(st.floats(min_value=0, max_value=30)),
            "estimated_public_wait_minutes": draw(st.floats(min_value=0, max_value=120)),
            "throughput_per_hour": draw(st.integers(min_value=0, max_value=200)),
            "slowest_lane_id": draw(st.one_of(st.none(), st.from_regex(r"[a-z0-9_-]{1,8}", fullmatch=True))),
            "confidence_score": draw(st.floats(min_value=0.0, max_value=1.0)),
        },
    )


# Feature: station-stats-api, Property 15: Unconfigured client skips submission and reports not-configured
@settings(max_examples=100, deadline=None)
@given(snapshot=arbitrary_snapshot(), config=unconfigured_config())
def test_unconfigured_client_skips_submission_and_reports_not_configured(
    snapshot: Snapshot,
    config: ClientConfig,
) -> None:
    """For any produced snapshot, when either API_Base_URL or Client_Credential
    is unconfigured, the LaneSight_Client:

    1. Makes no Submission_Attempt (transport.calls == []).
    2. Buffer is empty (snapshot dropped).
    3. Notification state has category NOT_CONFIGURED and visible=True.
    """
    # **Validates: Requirements 7.6**
    buffer = PendingSnapshotBuffer()
    transport = _RecordingTransport()

    # Collect retry scheduler calls to prevent actual timer creation.
    retry_calls: list[float] = []

    def fake_retry_scheduler(delay: float, callback) -> None:
        retry_calls.append(delay)

    # Track notification states.
    notifications: list[NotificationState] = []

    client = LaneSightClient(
        config=config,
        buffer=buffer,
        station_identifier=snapshot.station_id,
        transport=transport,
        notification_sink=notifications.append,
        retry_scheduler=fake_retry_scheduler,
    )

    # Produce the snapshot — the client should detect unconfigured state and skip.
    client.on_snapshot_produced(snapshot)

    # Assert: no submission attempt was made (transport.calls == []).
    assert transport.calls == [], (
        f"Expected no submission attempts for unconfigured client, "
        f"got {len(transport.calls)} call(s). Config: {config}"
    )

    # Assert: buffer is empty (snapshot dropped).
    assert len(buffer) == 0, (
        f"Expected buffer empty (snapshot dropped) for unconfigured client, "
        f"got {len(buffer)} snapshot(s) in buffer. Config: {config}"
    )

    # Assert: notification state has category NOT_CONFIGURED and visible=True.
    assert client.notification_state is not None, (
        "Expected a notification state to be set for unconfigured client"
    )
    assert client.notification_state.category == NotificationCategory.NOT_CONFIGURED, (
        f"Expected NOT_CONFIGURED category, got {client.notification_state.category}. "
        f"Config: {config}"
    )
    assert client.notification_state.visible is True, (
        f"Expected notification visible=True for unconfigured client, "
        f"got visible={client.notification_state.visible}. Config: {config}"
    )

    # Assert: no retry was scheduled.
    assert retry_calls == [], (
        f"Expected no retry scheduled for unconfigured client, "
        f"got {len(retry_calls)} retry call(s)"
    )
