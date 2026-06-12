"""Wires the LaneSightClient into the GUI application lifecycle.

Creates a LaneSightClient from the persisted AppSettings and provides
:meth:`publish_snapshot` to convert a :class:`gui.metrics.StationMetrics`
into a Station_Metric_Snapshot and submit it to the Station_Stats_API.

For live/stream mode, a periodic timer calls publish at a configurable
interval (default 30s) so the public dashboard stays fresh.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Timer
from typing import TYPE_CHECKING

from lanesight_client import (
    ClientConfig,
    LaneSightClient,
    PendingSnapshotBuffer,
    Snapshot,
)

if TYPE_CHECKING:
    from gui.metrics import StationMetrics
    from gui.settings import SettingsManager

logger = logging.getLogger(__name__)

#: How often (seconds) to auto-publish during live/stream processing.
LIVE_PUBLISH_INTERVAL_SECONDS: float = 30.0


def _build_client_config(settings: "SettingsManager") -> ClientConfig:
    """Build a ClientConfig from the current AppSettings."""
    s = settings.get()
    return ClientConfig(
        api_base_url=s.api_base_url or None,
        client_credential=s.client_credential or None,
    )


def _metrics_to_snapshot_payload(
    metrics: "StationMetrics", station_id: str
) -> dict:
    """Convert a StationMetrics into the Station_Metric_Snapshot JSON payload.

    The API validation (station-stats-api Req 2.2/2.3) requires the four count
    fields (vehicles_in_queue, vehicles_in_bay, active_lanes,
    throughput_per_hour) to be strict integers, and the three minute fields plus
    confidence_score to be numbers. Coerce accordingly so submissions are not
    rejected with HTTP 422.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "station_id": station_id,
        "timestamp": now,
        "vehicles_in_queue": int(metrics.vehicles_in_queue),
        "vehicles_in_bay": int(metrics.completed_vehicles),
        "active_lanes": int(metrics.active_lanes),
        "average_queue_wait_minutes": round(metrics.average_queue_wait_minutes or 0, 2),
        "average_inspection_minutes": round(metrics.average_inspection_minutes or 0, 2),
        "estimated_public_wait_minutes": round(metrics.estimated_public_wait_minutes or 0, 2),
        "throughput_per_hour": int(round(metrics.throughput_per_hour)),
        "slowest_lane_id": None,
        "confidence_score": 0.82,
    }


class ApiPublisher:
    """Manages snapshot publishing to the Station_Stats_API.

    Constructed once at app startup. Call :meth:`publish_snapshot` after
    computing station metrics (end of file, or periodically during stream).
    """

    def __init__(self, settings: "SettingsManager") -> None:
        self._settings = settings
        config = _build_client_config(settings)
        self._station_id_source = lambda: settings.get().station_id
        self._client = LaneSightClient(
            config=config,
            buffer=PendingSnapshotBuffer(),
            station_identifier=self._station_id_source,
        )
        self._live_timer: Timer | None = None
        self._last_metrics: "StationMetrics | None" = None

    def publish_snapshot(self, metrics: "StationMetrics") -> None:
        """Convert metrics to a snapshot and submit via the client."""
        self._last_metrics = metrics
        station_id = self._station_id_source() or "unknown"
        payload = _metrics_to_snapshot_payload(metrics, station_id)
        snapshot = Snapshot(
            station_id=station_id,
            timestamp=payload["timestamp"],
            payload=payload,
        )
        try:
            self._client.on_snapshot_produced(snapshot)
            logger.info(
                "Published snapshot for station %s (wait=%s min)",
                station_id,
                metrics.estimated_public_wait_minutes,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to publish snapshot", exc_info=True)

    def start_live_publishing(self) -> None:
        """Start a periodic timer that re-publishes the latest metrics."""
        self.stop_live_publishing()
        self._schedule_next()

    def stop_live_publishing(self) -> None:
        """Stop the periodic live-publishing timer."""
        if self._live_timer is not None:
            self._live_timer.cancel()
            self._live_timer = None

    def _schedule_next(self) -> None:
        """Schedule the next live publish after the interval."""
        self._live_timer = Timer(
            LIVE_PUBLISH_INTERVAL_SECONDS, self._on_live_tick
        )
        self._live_timer.daemon = True
        self._live_timer.start()

    def _on_live_tick(self) -> None:
        """Callback: re-publish the latest metrics if available."""
        if self._last_metrics is not None:
            self.publish_snapshot(self._last_metrics)
        self._schedule_next()

    def refresh_config(self) -> None:
        """Rebuild the client config from current settings (e.g. after edit)."""
        config = _build_client_config(self._settings)
        self._client._config = config
