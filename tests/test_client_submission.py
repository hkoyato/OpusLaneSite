"""Unit tests for LaneSightClient enqueue, config check, and submission (task 11.1).

These cover the scope of design "LaneSight_Client" responsibilities 1-3:
stamping + enqueue (Req 7.1, 7.2), the unconfigured drop + not-configured
notification (Req 7.6), and the configured HTTPS submission carrying the
credential with a 10s timeout (Req 7.5, 7.7). A fake transport stands in for the
network so no real requests are made. Outcome handling / retry / drain is task
11.2 and is intentionally not asserted here.
"""

from __future__ import annotations

import pytest

from lanesight_client import (
    ClientConfig,
    LaneSightClient,
    NotificationCategory,
    PendingSnapshotBuffer,
    Snapshot,
    SubmitOutcome,
)
from lanesight_client.client import SUBMIT_TIMEOUT_SECONDS, CREDENTIAL_HEADER


class FakeTransport:
    """Records the single most recent submission and returns a fixed status."""

    def __init__(self, status_code: int = 201) -> None:
        self.status_code = status_code
        self.calls: list[dict] = []

    def post(self, url, *, json_body, headers, timeout):
        if not url.lower().startswith("https://"):
            raise ValueError("Snapshot submissions must be made over HTTPS")
        self.calls.append(
            {"url": url, "json_body": json_body, "headers": headers, "timeout": timeout}
        )

        class _Resp:
            status_code = self.status_code

        return _Resp()


def _snapshot(station_id: str = "demo_station_01") -> Snapshot:
    payload = {
        "station_id": station_id,
        "timestamp": "2026-06-12T13:45:00Z",
        "vehicles_in_queue": 9,
    }
    return Snapshot(station_id=station_id, timestamp="2026-06-12T13:45:00Z", payload=payload)


def test_configured_submits_over_https_with_credential_and_timeout():
    transport = FakeTransport(status_code=201)
    config = ClientConfig(
        api_base_url="https://api.example.com", client_credential="secret-key"
    )
    client = LaneSightClient(
        config, PendingSnapshotBuffer(), "demo_station_01", transport=transport
    )

    client.on_snapshot_produced(_snapshot())

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://api.example.com/stations/demo_station_01/snapshot"
    assert call["headers"][CREDENTIAL_HEADER] == "secret-key"
    assert call["timeout"] == SUBMIT_TIMEOUT_SECONDS == 10.0
    assert call["json_body"]["station_id"] == "demo_station_01"


def test_station_id_stamped_from_callable_provider():
    transport = FakeTransport()
    config = ClientConfig(
        api_base_url="https://api.example.com", client_credential="k"
    )
    active = {"id": "lane_station_42"}
    client = LaneSightClient(
        config, PendingSnapshotBuffer(), lambda: active["id"], transport=transport
    )

    # Produced with a different station_id; client stamps the active one.
    client.on_snapshot_produced(_snapshot(station_id="stale_id"))

    call = transport.calls[0]
    assert call["url"].endswith("/stations/lane_station_42/snapshot")
    assert call["json_body"]["station_id"] == "lane_station_42"


@pytest.mark.parametrize(
    "base_url,credential",
    [(None, "k"), ("https://api.example.com", None), (None, None), ("", "")],
)
def test_unconfigured_drops_snapshot_and_notifies(base_url, credential):
    transport = FakeTransport()
    config = ClientConfig(api_base_url=base_url, client_credential=credential)
    buffer = PendingSnapshotBuffer()
    client = LaneSightClient(config, buffer, "demo_station_01", transport=transport)

    client.on_snapshot_produced(_snapshot())

    # No submission attempted, snapshot dropped from the buffer (Req 7.6).
    assert transport.calls == []
    assert client.buffer_count() == 0
    state = client.notification_state
    assert state is not None
    assert state.visible is True
    assert state.category is NotificationCategory.NOT_CONFIGURED


def test_attempt_submit_classifies_status_codes():
    config = ClientConfig(
        api_base_url="https://api.example.com", client_credential="k"
    )
    snap = _snapshot()
    cases = {
        201: SubmitOutcome.PUBLISHED,
        200: SubmitOutcome.DUPLICATE,
        400: SubmitOutcome.DISCARDED,
        422: SubmitOutcome.DISCARDED,
        401: SubmitOutcome.RETRY,
        403: SubmitOutcome.RETRY,
        503: SubmitOutcome.RETRY,
    }
    for status, expected in cases.items():
        client = LaneSightClient(
            config, PendingSnapshotBuffer(), "demo_station_01",
            transport=FakeTransport(status_code=status),
        )
        assert client._attempt_submit(snap) is expected


def test_timeout_or_network_error_is_retryable():
    class TimingOutTransport:
        def post(self, url, *, json_body, headers, timeout):
            raise TimeoutError("timed out")

    config = ClientConfig(
        api_base_url="https://api.example.com", client_credential="k"
    )
    client = LaneSightClient(
        config, PendingSnapshotBuffer(), "demo_station_01",
        transport=TimingOutTransport(),
    )
    assert client._attempt_submit(_snapshot()) is SubmitOutcome.RETRY


def test_notification_sink_receives_state():
    received = []
    config = ClientConfig(api_base_url=None, client_credential=None)
    client = LaneSightClient(
        config, PendingSnapshotBuffer(), "demo_station_01",
        transport=FakeTransport(), notification_sink=received.append,
    )

    client.on_snapshot_produced(_snapshot())

    assert len(received) == 1
    assert received[0].category is NotificationCategory.NOT_CONFIGURED
