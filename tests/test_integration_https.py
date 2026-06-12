"""Integration tests for HTTPS-only enforcement (Task 14.3).

TLS enforcement in the Station Statistics API is a two-layer defense:

1. **Gateway layer (infra/template.yaml):**
   API Gateway only exposes HTTPS endpoints — there is no HTTP listener.
   The optional custom domain pins ``SecurityPolicy: TLS_1_2``. An
   unencrypted HTTP request simply cannot reach the Lambda handlers because
   no plaintext port exists. This is documented in the template comments
   under the ``StationStatsApi`` and ``ApiDomainName`` resources (Req 3.4,
   3.6).

2. **Client-side transport layer (lanesight_client.client.UrllibSnapshotTransport):**
   Before any network I/O occurs, the transport validates that the target
   URL starts with ``https://``. A non-HTTPS URL raises ``ValueError``
   immediately — nothing is sent, nothing is stored, nothing is returned.
   This provides defense-in-depth even if a misconfigured ``api_base_url``
   bypasses the gateway's TLS constraint.

These tests exercise layer 2 (the client-side enforcement) in isolation
since the gateway layer is infrastructure that cannot be exercised without
a deployed stack. The tests confirm that unencrypted requests are rejected
before the handler, nothing is stored or returned (Req 3.4, 3.6).

Validates: Requirements 3.4, 3.6
"""

from __future__ import annotations

import pytest

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.client import (
    LaneSightClient,
    UrllibSnapshotTransport,
)
from lanesight_client.models import ClientConfig, Snapshot


# ---------------------------------------------------------------------------
# 1. UrllibSnapshotTransport rejects http:// URLs with ValueError
# ---------------------------------------------------------------------------


class TestTransportHttpsEnforcement:
    """UrllibSnapshotTransport raises ValueError for non-https URLs."""

    def test_http_url_raises_valueerror(self) -> None:
        """A plain http:// URL is rejected before any request is made."""
        transport = UrllibSnapshotTransport()

        with pytest.raises(ValueError, match="HTTPS"):
            transport.post(
                "http://stats.example.com/stations/demo/snapshot",
                json_body={"station_id": "demo", "timestamp": "2026-01-01T00:00:00Z"},
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )

    def test_http_url_no_network_io(self) -> None:
        """The rejection happens synchronously — no socket is opened.

        We verify this indirectly: if a network request were attempted to a
        non-routable address, the call would block or raise OSError/TimeoutError,
        not ValueError. The ValueError proves no I/O occurred.
        """
        transport = UrllibSnapshotTransport()

        with pytest.raises(ValueError):
            transport.post(
                "http://192.0.2.1/stations/test_station/snapshot",
                json_body={"key": "value"},
                headers={},
                timeout=0.001,  # Irrelevant — never reaches the network
            )

    def test_http_uppercase_scheme_rejected(self) -> None:
        """Mixed-case 'Http://' is also rejected (case-insensitive check)."""
        transport = UrllibSnapshotTransport()

        with pytest.raises(ValueError, match="HTTPS"):
            transport.post(
                "Http://stats.example.com/stations/demo/snapshot",
                json_body={},
                headers={},
                timeout=10.0,
            )

    def test_empty_url_rejected(self) -> None:
        """An empty or non-https URL is rejected."""
        transport = UrllibSnapshotTransport()

        with pytest.raises(ValueError):
            transport.post(
                "",
                json_body={},
                headers={},
                timeout=10.0,
            )


# ---------------------------------------------------------------------------
# 2. LaneSightClient with http:// api_base_url: transport rejects the request
# ---------------------------------------------------------------------------


def _make_snapshot(station_id: str = "demo_station") -> Snapshot:
    """Create a minimal valid Snapshot for testing."""
    return Snapshot(
        station_id=station_id,
        timestamp="2026-06-12T13:45:00Z",
        payload={
            "station_id": station_id,
            "timestamp": "2026-06-12T13:45:00Z",
            "vehicles_in_queue": 5,
            "vehicles_in_bay": 2,
            "active_lanes": 3,
            "average_queue_wait_minutes": 10.0,
            "average_inspection_minutes": 5.0,
            "estimated_public_wait_minutes": 12.0,
            "throughput_per_hour": 20,
            "slowest_lane_id": "lane_1",
            "confidence_score": 0.9,
        },
    )


class TestClientHttpsEnforcement:
    """LaneSightClient with an http:// base URL cannot publish snapshots."""

    def test_http_base_url_rejected_before_handler(self) -> None:
        """When UrllibSnapshotTransport encounters an http:// URL, the
        ValueError propagates immediately — no data reaches the handler,
        nothing is stored, nothing is returned (Req 3.4, 3.6).

        The client's error handling catches TimeoutError and OSError (real
        network failures) but intentionally lets ValueError propagate because
        it indicates a programming/configuration error, not a transient outage.
        This is the correct defense-in-depth behavior: the misconfiguration
        is surfaced loudly rather than silently retried forever.
        """
        config = ClientConfig(
            api_base_url="http://insecure.example.com",
            client_credential="test-credential-abc",
        )
        buffer = PendingSnapshotBuffer()

        client = LaneSightClient(
            config=config,
            buffer=buffer,
            station_identifier="demo_station",
            # Use the real UrllibSnapshotTransport — it will reject http://
            transport=UrllibSnapshotTransport(),
            retry_scheduler=lambda _delay, _fn: None,  # no-op scheduler
        )

        snapshot = _make_snapshot()

        # The ValueError proves the request was rejected before the handler —
        # no HTTP request was made, nothing was stored or returned.
        with pytest.raises(ValueError, match="HTTPS"):
            client.on_snapshot_produced(snapshot)

    def test_transport_valueerror_prevents_data_transmission(self) -> None:
        """Direct _attempt_submit with http:// base raises ValueError.

        This confirms the defense-in-depth: the transport's ValueError
        propagates before any data is transmitted over an unencrypted channel.
        The HTTPS check runs before socket creation, so nothing is stored or
        returned on the server side.
        """
        config = ClientConfig(
            api_base_url="http://insecure.example.com",
            client_credential="test-credential-abc",
        )
        buffer = PendingSnapshotBuffer()

        client = LaneSightClient(
            config=config,
            buffer=buffer,
            station_identifier="demo_station",
            transport=UrllibSnapshotTransport(),
            retry_scheduler=lambda _delay, _fn: None,
        )

        snapshot = _make_snapshot()

        # ValueError proves no network I/O occurred — the request was
        # rejected before the handler; nothing stored/returned.
        with pytest.raises(ValueError, match="HTTPS"):
            client._attempt_submit(snapshot)
