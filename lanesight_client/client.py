"""LaneSight_Client submission logic.

This module implements :class:`LaneSightClient`, the component that lives inside
the ``GUI_Application`` and publishes ``Station_Metric_Snapshot`` records to the
``Snapshot_Endpoint`` of the Station_Stats_API.

Scope of this module (task 11.1):

- **Enqueue + stamp (Req 7.1, 7.2):** ``on_snapshot_produced`` stamps the
  snapshot's ``station_id`` with the active ``Station_Identifier`` at production
  time and adds it to the ``Pending_Snapshot_Buffer``.
- **Configuration check (Req 7.6):** if either ``API_Base_URL`` or
  ``Client_Credential`` is unconfigured, the client skips the attempt, drops the
  snapshot from the buffer, and surfaces a ``NOT_CONFIGURED``
  ``Connectivity_Notification`` synchronously (well within the 2s budget).
- **Submission attempt (Req 7.5, 7.7):** when configured, the snapshot is sent
  as a JSON request body over HTTPS to ``POST /stations/{station_id}/snapshot``
  presenting the ``Client_Credential``, with a 10-second timeout.

Outcome handling, buffer draining, eviction notification, and retry scheduling
are implemented separately in task 11.2; ``_attempt_submit`` returns a
:class:`SubmitOutcome` so that step can consume it. Backoff is not duplicated
here — it is delegated to :func:`lanesight_client.backoff.next_backoff`.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol, Union, runtime_checkable

from station_stats_api.http_result import (
    HTTP_BAD_REQUEST,
    HTTP_CREATED,
    HTTP_OK,
    HTTP_UNPROCESSABLE_ENTITY,
)

from .backoff import next_backoff
from .buffer import PendingSnapshotBuffer
from .models import ClientConfig, Snapshot, SubmitOutcome
from .notification import (
    NotificationEvent,
    NotificationState,
    event_from_status,
    reduce_notification,
)

__all__ = [
    "LaneSightClient",
    "SnapshotTransport",
    "UrllibSnapshotTransport",
    "RetryScheduler",
    "SUBMIT_TIMEOUT_SECONDS",
    "CREDENTIAL_HEADER",
    "SNAPSHOT_PATH_TEMPLATE",
]

# The Submission_Attempt timeout: an attempt that has not received a response
# within this many seconds is treated as failed (Req 7.5).
SUBMIT_TIMEOUT_SECONDS: float = 10.0

# HTTP header that carries the Client_Credential. API Gateway's credential
# authorizer reads the API key from this header (design "Endpoints").
CREDENTIAL_HEADER: str = "x-api-key"

# Snapshot resource path template (design "Endpoints").
SNAPSHOT_PATH_TEMPLATE: str = "/stations/{station_id}/snapshot"

# A station-identifier source: either a plain (optional) string or a zero-arg
# callable returning the active Station_Identifier at production time.
StationIdentifier = Union[str, None, Callable[[], "str | None"]]

# A retry scheduler: invoked with the backoff ``delay`` (seconds) and a
# zero-argument ``callback`` that resumes the drain pass. Injected so retry
# timing is deterministic in tests (no real ``time.sleep`` in the hot path).
RetryScheduler = Callable[[float, Callable[[], None]], None]


def _default_retry_scheduler(delay: float, callback: Callable[[], None]) -> None:
    """Default :data:`RetryScheduler`: fire ``callback`` after ``delay`` seconds.

    Uses a daemon :class:`threading.Timer` so the GUI thread is never blocked
    (no ``time.sleep`` on the hot path) and a pending retry never keeps the
    process alive on shutdown. Tests inject a synchronous/recording scheduler.
    """
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()


@runtime_checkable
class _SupportsStatusCode(Protocol):
    """Minimal response contract: a requests-style ``status_code`` attribute."""

    @property
    def status_code(self) -> int: ...


class SnapshotTransport(Protocol):
    """Injectable, requests-style HTTP transport for snapshot submission.

    Implementations submit a single snapshot and return any object exposing an
    integer ``status_code``. They MUST enforce HTTPS and MUST raise
    :class:`TimeoutError`/:class:`OSError` (or a subclass, e.g.
    ``requests.exceptions.RequestException``) on timeout or network failure so
    the client can classify the attempt as retryable.
    """

    def post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> _SupportsStatusCode: ...


@dataclass(frozen=True)
class _Response:
    """A tiny response wrapper carrying just the HTTP status code."""

    status_code: int


class UrllibSnapshotTransport:
    """Default :class:`SnapshotTransport` built on the standard library.

    Uses ``urllib`` so the client has no third-party dependency by default while
    remaining injectable for tests. HTTPS is enforced: a non-HTTPS URL raises
    ``ValueError`` before any request is made (Req 7.7). HTTP error statuses
    (4xx/5xx) are returned as a response with that status code; only genuine
    timeout/network failures propagate as ``OSError``/``TimeoutError``.
    """

    def post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        if not url.lower().startswith("https://"):
            raise ValueError("Snapshot submissions must be made over HTTPS")

        data = json.dumps(json_body).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                return _Response(status_code=int(status))
        except urllib.error.HTTPError as exc:
            # A real HTTP response with a 4xx/5xx status — not a transport
            # failure. Surface the status so the client can classify it.
            return _Response(status_code=int(exc.code))


class LaneSightClient:
    """Publishes produced snapshots to the Station_Stats_API.

    The client is constructed with everything it needs injected so it is fully
    testable without a real network or GUI:

    Args:
        config: The :class:`ClientConfig` holding ``api_base_url`` and
            ``client_credential`` (the credential is never logged).
        buffer: The bounded :class:`PendingSnapshotBuffer` holding snapshots
            awaiting publication.
        station_identifier: The active ``Station_Identifier`` source — either a
            plain string (or ``None``) or a zero-argument callable resolved at
            snapshot-production time (Req 7.2).
        transport: An injectable :class:`SnapshotTransport`. Defaults to
            :class:`UrllibSnapshotTransport`.
        notification_sink: Optional callback invoked with each derived
            :class:`NotificationState` so the GUI surface can update. The latest
            state is also available via :attr:`notification_state`.
        retry_scheduler: Optional :data:`RetryScheduler` used to schedule a
            retry of the drain pass after the backoff delay. Defaults to a
            daemon-timer scheduler; tests inject a deterministic one.
        logger: Optional :class:`logging.Logger` for recording terminal
            rejection reasons (Req 7.4). The ``Client_Credential`` is never
            logged. Defaults to this module's logger.
    """

    def __init__(
        self,
        config: ClientConfig,
        buffer: PendingSnapshotBuffer,
        station_identifier: StationIdentifier,
        *,
        transport: SnapshotTransport | None = None,
        notification_sink: Callable[[NotificationState], None] | None = None,
        retry_scheduler: RetryScheduler | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._buffer = buffer
        self._station_identifier = station_identifier
        self._transport: SnapshotTransport = transport or UrllibSnapshotTransport()
        self._notification_sink = notification_sink
        self._notification_state: NotificationState | None = None
        self._retry_scheduler: RetryScheduler = (
            retry_scheduler or _default_retry_scheduler
        )
        self._logger = logger or logging.getLogger(__name__)
        # Count of consecutive failed Submission_Attempts since the last
        # success. Drives the backoff delay (Req 8.2) and is reset to 0 on any
        # successful attempt.
        self._consecutive_failures = 0

    # --- Public API -----------------------------------------------------------

    def on_snapshot_produced(self, snapshot: Snapshot) -> None:
        """Enqueue a produced snapshot and publish buffered snapshots if configured.

        Stamps the snapshot's ``station_id`` with the active Station_Identifier
        (Req 7.2) and adds it to the Pending_Snapshot_Buffer (Req 7.1). If the
        add overflows the buffer, the evicted oldest snapshot triggers a
        permanent-drop notification (Req 8.4, 9.7). When the client is
        unconfigured it drops the snapshot and surfaces a not-configured
        notification synchronously (Req 7.6). When configured it runs a drain
        pass that publishes buffered snapshots oldest-first over HTTPS with a
        10s timeout (Req 7.5, 7.7, 8.5).

        Args:
            snapshot: The snapshot just produced by the detection pipeline.
        """
        stamped = self._stamp(snapshot)  # Req 7.2
        evicted = self._buffer.add(stamped)  # Req 7.1, 8.4

        if not self._is_configured():
            # Req 7.6: skip the attempt, drop the snapshot, and surface a
            # not-configured notification immediately (well within 2s).
            self._buffer.remove(stamped)
            self._notify(event_from_status(configured=False))
            return

        # Req 9.7: a buffer-overflow eviction means an unpublished snapshot was
        # permanently dropped — surface that before attempting to publish.
        if evicted is not None:
            self._notify(NotificationEvent.EVICTION)

        # Req 7.5, 7.7 + Req 8.5: drain the buffer oldest-first, publishing each
        # snapshot over HTTPS with the credential. The pass stops on the first
        # retryable failure and resumes after the next backoff interval.
        self._drain_buffer()

    def buffer_count(self) -> int:
        """Return the current number of snapshots held in the buffer."""
        return len(self._buffer)

    @property
    def notification_state(self) -> NotificationState | None:
        """The most recently derived Connectivity_Notification state, if any."""
        return self._notification_state

    # --- Draining + outcome handling ------------------------------------------

    def drain(self) -> None:
        """Publish buffered snapshots oldest-first (public entry point).

        Runs a single publishing pass over the Pending_Snapshot_Buffer in
        ascending timestamp order. Successfully published or terminally
        rejected snapshots are removed; the pass stops on the first retryable
        failure, retaining the remaining snapshots in chronological order, and
        schedules a resume after the next backoff interval (Req 8.5, 8.7).
        """
        self._drain_buffer()

    def _drain_buffer(self) -> None:
        """Perform one oldest-first publishing pass over the buffer.

        For each snapshot, oldest first (``peek_oldest``):

        - ``201`` / duplicate ``200`` -> remove it (Req 7.3, 8.6), reset the
          backoff counter, and clear the Connectivity_Notification, then
          continue to the next-oldest snapshot.
        - ``400`` / ``422`` -> discard it and log the rejection reason
          (Req 7.4); retrying never succeeds, so continue the pass.
        - timeout / network / ``5xx`` / ``401`` / ``403`` -> retain it
          (Req 8.1), surface the appropriate notification (OUTAGE vs AUTH),
          increment the failure counter, schedule a backoff retry, and stop the
          pass (Req 8.3, 8.7).
        """
        while True:
            snapshot = self._buffer.peek_oldest()
            if snapshot is None:
                return  # Buffer fully drained.

            outcome, event, http_status = self._attempt_submit_detailed(snapshot)

            if outcome in (SubmitOutcome.PUBLISHED, SubmitOutcome.DUPLICATE):
                # Req 7.3, 8.6: published -> remove. Reset backoff and clear the
                # notice (publishing has resumed, Req 9.3).
                self._buffer.remove(snapshot)
                self._consecutive_failures = 0
                self._notify(NotificationEvent.SUCCESS)
                continue

            if outcome is SubmitOutcome.DISCARDED:
                # Req 7.4: terminal rejection -> discard + log; keep draining.
                self._buffer.remove(snapshot)
                self._log_rejection(snapshot, http_status)
                continue

            # Req 8.1, 8.7: retryable failure -> retain, notify, back off, stop.
            self._consecutive_failures += 1
            if event is not None:
                self._notify(event)
            delay = self._next_backoff(self._consecutive_failures)
            self._schedule_retry(delay)
            return

    def _schedule_retry(self, delay: float) -> None:
        """Schedule a resume of the drain pass after ``delay`` seconds (Req 8.7)."""
        self._retry_scheduler(delay, self._drain_buffer)

    def _log_rejection(self, snapshot: Snapshot, http_status: int | None) -> None:
        """Record the rejection reason for a discarded snapshot (Req 7.4).

        Logs only the ``station_id``, ``timestamp``, and HTTP status — never the
        ``Client_Credential`` or any plate/driver-identifying data.
        """
        self._logger.warning(
            "Station_Metric_Snapshot rejected by Station_Stats_API; "
            "discarding from Pending_Snapshot_Buffer. "
            "station_id=%s timestamp=%s http_status=%s",
            snapshot.station_id,
            snapshot.timestamp,
            http_status,
        )

    # --- Submission -----------------------------------------------------------

    def _attempt_submit(self, snapshot: Snapshot) -> SubmitOutcome:
        """Make a single HTTPS Submission_Attempt and return its outcome.

        Thin wrapper over :meth:`_attempt_submit_detailed` preserving the
        original return contract (a bare :class:`SubmitOutcome`) for callers and
        tests that only need the outcome.

        Args:
            snapshot: The stamped snapshot to publish.

        Returns:
            The :class:`SubmitOutcome` derived from the attempt.
        """
        outcome, _event, _status = self._attempt_submit_detailed(snapshot)
        return outcome

    def _attempt_submit_detailed(
        self, snapshot: Snapshot
    ) -> tuple[SubmitOutcome, NotificationEvent | None, int | None]:
        """Make a single HTTPS Submission_Attempt and classify it fully.

        Sends the snapshot payload as a JSON request body to
        ``POST /stations/{station_id}/snapshot`` at the configured
        ``API_Base_URL``, presenting the ``Client_Credential`` and applying the
        10-second timeout (Req 7.5, 7.7). Distinguishes auth failures
        (``401``/``403`` -> AUTH) from outages (timeout/network/``5xx`` ->
        OUTAGE) so the notification can tell them apart (Req 9.1, 9.5).

        Args:
            snapshot: The stamped snapshot to publish.

        Returns:
            A tuple of ``(outcome, event, http_status)`` where ``event`` is the
            notification-relevant :class:`NotificationEvent` for the attempt
            (``None`` for a terminal discard) and ``http_status`` is the HTTP
            status code received, or ``None`` for a timeout/network failure.
        """
        url = self._snapshot_url(snapshot.station_id)
        headers = {
            "Content-Type": "application/json",
            CREDENTIAL_HEADER: self._config.client_credential or "",
        }
        try:
            response = self._transport.post(
                url,
                json_body=snapshot.payload,
                headers=headers,
                timeout=SUBMIT_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError):
            # Timeout (Req 7.5) or network error -> retryable outage (Req 8.1).
            return SubmitOutcome.RETRY, NotificationEvent.OUTAGE, None

        status = response.status_code
        outcome = self._classify_status(status)
        if outcome in (SubmitOutcome.PUBLISHED, SubmitOutcome.DUPLICATE):
            return outcome, NotificationEvent.SUCCESS, status
        if outcome is SubmitOutcome.DISCARDED:
            return outcome, None, status
        # Retryable status: AUTH for 401/403, OUTAGE for 5xx/unexpected.
        return outcome, event_from_status(http_status=status), status

    def _next_backoff(self, consecutive_failures: int) -> float:
        """Delay before the next attempt; delegates to :func:`next_backoff`."""
        return next_backoff(consecutive_failures)

    # --- Helpers --------------------------------------------------------------

    def _is_configured(self) -> bool:
        """Return whether both API_Base_URL and Client_Credential are set."""
        return bool(self._config.api_base_url) and bool(
            self._config.client_credential
        )

    def _active_station_id(self) -> str | None:
        """Resolve the active Station_Identifier from the configured source."""
        source = self._station_identifier
        if callable(source):
            return source()
        return source

    def _stamp(self, snapshot: Snapshot) -> Snapshot:
        """Return a copy of ``snapshot`` stamped with the active station id.

        The ``station_id`` field and the ``station_id`` key inside ``payload``
        are both set to the active Station_Identifier at production time so the
        submitted body and the URL agree (Req 7.2).
        """
        station_id = self._active_station_id()
        payload = dict(snapshot.payload)
        payload["station_id"] = station_id
        return Snapshot(
            station_id=station_id,
            timestamp=snapshot.timestamp,
            payload=payload,
        )

    def _snapshot_url(self, station_id: str | None) -> str:
        """Build the Snapshot_Endpoint URL for ``station_id``."""
        base = (self._config.api_base_url or "").rstrip("/")
        return base + SNAPSHOT_PATH_TEMPLATE.format(station_id=station_id)

    @staticmethod
    def _classify_status(status_code: int) -> SubmitOutcome:
        """Map an HTTP status code to a :class:`SubmitOutcome`.

        ``201`` -> PUBLISHED, ``200`` -> DUPLICATE, ``400``/``422`` -> DISCARDED,
        and everything else (``401``/``403``/``5xx``/unexpected) -> RETRY. The
        differentiated handling of auth vs. outage failures lives in task 11.2.
        """
        if status_code == HTTP_CREATED:
            return SubmitOutcome.PUBLISHED
        if status_code == HTTP_OK:
            return SubmitOutcome.DUPLICATE
        if status_code in (HTTP_BAD_REQUEST, HTTP_UNPROCESSABLE_ENTITY):
            return SubmitOutcome.DISCARDED
        return SubmitOutcome.RETRY

    def _notify(self, event: NotificationEvent) -> None:
        """Derive and publish the Connectivity_Notification state for ``event``."""
        state = reduce_notification(event, len(self._buffer))
        self._notification_state = state
        if self._notification_sink is not None:
            self._notification_sink(state)
