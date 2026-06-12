"""Unit tests for timeout and no-max-attempts configuration.

Task 11.7 — Assert the 10s submission timeout is configured (Req 7.5) and no
fixed attempt cap is imposed (Req 8.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lanesight_client.client import (
    SUBMIT_TIMEOUT_SECONDS,
    LaneSightClient,
    SnapshotTransport,
)
from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.models import ClientConfig, Snapshot, SubmitOutcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeResponse:
    """Minimal response exposing only ``status_code``."""

    status_code: int


class _Always503Transport:
    """A transport that always returns HTTP 503 (retryable server error)."""

    def post(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        return _FakeResponse(status_code=503)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubmitTimeoutIs10Seconds:
    """Req 7.5: The LaneSight_Client SHALL apply a 10-second timeout."""

    def test_submit_timeout_is_10_seconds(self) -> None:
        """SUBMIT_TIMEOUT_SECONDS constant must equal 10.0."""
        assert SUBMIT_TIMEOUT_SECONDS == 10.0


class TestNoFixedMaxAttemptCap:
    """Req 8.3: The client retries indefinitely with no fixed max attempt count."""

    def test_no_fixed_max_attempt_cap(self) -> None:
        """After many consecutive drain failures the client never gives up.

        Create a configured LaneSightClient with a transport that always returns
        503. Produce a snapshot, then manually invoke ``drain`` many times (100).
        Assert that after each drain the retry scheduler is called again (no
        cap), the buffer still has the snapshot, and the client never gives up.
        Also assert no ``max_attempts`` attribute/constant exists that would cap
        retries.
        """
        # Track retry_scheduler invocations.
        retry_calls: list[tuple[float, Any]] = []

        def recording_scheduler(delay: float, callback: Any) -> None:
            retry_calls.append((delay, callback))

        config = ClientConfig(
            api_base_url="https://api.example.com",
            client_credential="test-key-secret",
        )
        buffer = PendingSnapshotBuffer()
        transport = _Always503Transport()

        client = LaneSightClient(
            config=config,
            buffer=buffer,
            station_identifier="test_station",
            transport=transport,
            retry_scheduler=recording_scheduler,
        )

        # Produce a snapshot — this triggers one drain attempt internally.
        snapshot = Snapshot(
            station_id="test_station",
            timestamp="2026-06-12T21:45:00Z",
            payload={
                "station_id": "test_station",
                "timestamp": "2026-06-12T21:45:00Z",
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
        client.on_snapshot_produced(snapshot)

        # The initial on_snapshot_produced triggers a drain that fails and
        # schedules one retry. The snapshot must still be in the buffer.
        assert client.buffer_count() == 1
        assert len(retry_calls) == 1

        # Now simulate 99 more drain attempts (total 100 failures) — each time
        # the client should retain the snapshot and schedule another retry.
        for i in range(99):
            retry_calls.clear()
            client.drain()
            assert client.buffer_count() == 1, (
                f"Buffer empty after drain #{i + 2} — client gave up"
            )
            assert len(retry_calls) == 1, (
                f"No retry scheduled after drain #{i + 2} — client gave up"
            )

        # After 100 consecutive failures the client still has not discarded
        # the snapshot and is still scheduling retries — no cap.
        assert client.buffer_count() == 1

        # Assert there is no max_attempts attribute/constant on the client
        # or its class that would cap retries.
        assert not hasattr(client, "max_attempts")
        assert not hasattr(client, "MAX_ATTEMPTS")
        assert not hasattr(client, "_max_attempts")
        assert not hasattr(LaneSightClient, "max_attempts")
        assert not hasattr(LaneSightClient, "MAX_ATTEMPTS")
        assert not hasattr(LaneSightClient, "_max_attempts")
