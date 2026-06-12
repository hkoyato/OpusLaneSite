"""LaneSight_Client — GUI-side component that publishes snapshots to the API.

This package holds the client-side logic that lives inside the GUI_Application:
the bounded ``PendingSnapshotBuffer``, the exponential backoff scheduler, the
submission/retry/eviction/duplicate handling, and the ``Connectivity_Notification``
state reducer. Pure-logic seams are verified with Hypothesis property-based
tests (see ``tests/``).
"""

from __future__ import annotations

from .buffer import PendingSnapshotBuffer
from .client import (
    CREDENTIAL_HEADER,
    SNAPSHOT_PATH_TEMPLATE,
    SUBMIT_TIMEOUT_SECONDS,
    LaneSightClient,
    RetryScheduler,
    SnapshotTransport,
    UrllibSnapshotTransport,
)
from .models import ClientConfig, Snapshot, SubmitOutcome
from .notification import (
    NotificationCategory,
    NotificationEvent,
    NotificationState,
    event_from_status,
    reduce_notification,
)

__all__: list[str] = [
    "PendingSnapshotBuffer",
    "Snapshot",
    "ClientConfig",
    "SubmitOutcome",
    "NotificationCategory",
    "NotificationEvent",
    "NotificationState",
    "reduce_notification",
    "event_from_status",
    "LaneSightClient",
    "SnapshotTransport",
    "UrllibSnapshotTransport",
    "RetryScheduler",
    "SUBMIT_TIMEOUT_SECONDS",
    "CREDENTIAL_HEADER",
    "SNAPSHOT_PATH_TEMPLATE",
]
