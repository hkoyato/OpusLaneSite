"""Connectivity_Notification state reducer for the LaneSight_Client.

This is the *pure* logic that derives what the GUI's ``Connectivity_Notification``
should show, given the latest submission event plus the current
``Pending_Snapshot_Buffer`` count. It performs no I/O and holds no state, so it
can be exercised exhaustively by the Property 17 property test (task 13.2). The
GUI surface that binds to this state (orange ``#FF8200`` warning treatment +
text label) is implemented separately in task 13.3.

State derivation (design "Connectivity_Notification (GUI surface)", Req 9.1,
9.2, 9.3, 9.5, 9.7 and Req 7.6):

- Latest failure status ``401``/``403`` -> visible, ``AUTH`` category
  (authentication/authorization problem, distinct from an outage; Req 9.5).
- Timeout, network error, or ``5xx`` -> visible, ``OUTAGE`` category (Req 9.1).
- An eviction just occurred -> visible, ``PERMANENT_DROP`` category indicating
  unpublished snapshots are being permanently dropped (Req 9.7).
- Client unconfigured (no ``API_Base_URL`` / ``Client_Credential``) -> visible,
  ``NOT_CONFIGURED`` category (Req 7.6).
- A success (``201`` or duplicate ``200``) -> cleared/hidden, ``NONE`` category,
  indicating publishing has resumed (Req 9.3).

While visible, the state always carries the current ``Pending_Snapshot_Buffer``
count so the GUI can display it and keep it fresh (Req 9.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .models import SubmitOutcome

__all__ = [
    "NotificationCategory",
    "NotificationEvent",
    "NotificationState",
    "reduce_notification",
    "event_from_status",
]


class NotificationCategory(Enum):
    """The kind of Connectivity_Notification to surface (or none)."""

    NONE = auto()           # cleared / hidden (publishing healthy or resumed)
    OUTAGE = auto()         # timeout / network error / HTTP 5xx
    AUTH = auto()           # HTTP 401 / 403 (auth/authorization problem)
    NOT_CONFIGURED = auto()  # API_Base_URL / Client_Credential not configured
    PERMANENT_DROP = auto()  # buffer full: oldest snapshot evicted/dropped


class NotificationEvent(Enum):
    """The salient latest event the notification state is derived from.

    These collapse the richer submission outcomes / HTTP statuses into the
    distinctions that actually change what the operator is told.
    """

    SUCCESS = auto()         # 201 or duplicate 200 -> clear
    OUTAGE = auto()          # timeout / network / 5xx
    AUTH = auto()            # 401 / 403
    EVICTION = auto()        # a buffer overflow eviction just occurred
    NOT_CONFIGURED = auto()  # client missing API_Base_URL / Client_Credential


# Human-readable copy per category. Sentence case per Opus UI guidelines (§7).
# Auth copy is intentionally distinct from outage copy (Req 9.5).
_LABELS: dict[NotificationCategory, str] = {
    NotificationCategory.NONE: "Publishing active",
    NotificationCategory.OUTAGE: "Publishing interrupted",
    NotificationCategory.AUTH: "Authentication problem",
    NotificationCategory.NOT_CONFIGURED: "Publishing not configured",
    NotificationCategory.PERMANENT_DROP: "Dropping unpublished snapshots",
}

_MESSAGES: dict[NotificationCategory, str] = {
    NotificationCategory.NONE: "Statistics publishing has resumed.",
    NotificationCategory.OUTAGE: (
        "Statistics could not be published to the Station Stats API. "
        "Retrying automatically."
    ),
    NotificationCategory.AUTH: (
        "Statistics publishing failed due to an authentication or "
        "authorization problem, not a network outage. Check the client "
        "credential."
    ),
    NotificationCategory.NOT_CONFIGURED: (
        "Statistics publishing is not configured. Set the API base URL and "
        "client credential to publish station statistics."
    ),
    NotificationCategory.PERMANENT_DROP: (
        "The pending buffer is full. Unpublished snapshots are being "
        "permanently dropped until publishing recovers."
    ),
}

# Which categories are surfaced to the operator (visible) vs. hidden.
_VISIBLE_CATEGORIES = frozenset(
    {
        NotificationCategory.OUTAGE,
        NotificationCategory.AUTH,
        NotificationCategory.NOT_CONFIGURED,
        NotificationCategory.PERMANENT_DROP,
    }
)

# Map each latest event to the category it produces.
_EVENT_CATEGORY: dict[NotificationEvent, NotificationCategory] = {
    NotificationEvent.SUCCESS: NotificationCategory.NONE,
    NotificationEvent.OUTAGE: NotificationCategory.OUTAGE,
    NotificationEvent.AUTH: NotificationCategory.AUTH,
    NotificationEvent.EVICTION: NotificationCategory.PERMANENT_DROP,
    NotificationEvent.NOT_CONFIGURED: NotificationCategory.NOT_CONFIGURED,
}


@dataclass(frozen=True)
class NotificationState:
    """The derived presentation state for the Connectivity_Notification.

    Attributes:
        visible: Whether the notification should be shown at all.
        category: The kind of notification (drives copy and styling).
        buffer_count: The current number of snapshots held in the
            Pending_Snapshot_Buffer. Always populated so the GUI can display a
            live count while the notice is visible (Req 9.2).
        label: A short human-readable label for the category.
        message: A fuller human-readable message appropriate to the category.
    """

    visible: bool
    category: NotificationCategory
    buffer_count: int
    label: str
    message: str


def reduce_notification(
    event: NotificationEvent, buffer_count: int
) -> NotificationState:
    """Derive the Connectivity_Notification state from the latest event.

    Pure and side-effect free: the result depends only on ``event`` and
    ``buffer_count``, so the same inputs always yield the same state.

    Args:
        event: The most recent notification-relevant event (success, outage,
            auth failure, eviction, or not-configured).
        buffer_count: The current Pending_Snapshot_Buffer size. Surfaced while
            the notification is visible (Req 9.2).

    Returns:
        The :class:`NotificationState` the GUI should render.

    Raises:
        ValueError: If ``buffer_count`` is negative.
    """
    if buffer_count < 0:
        raise ValueError("buffer_count must be non-negative")

    category = _EVENT_CATEGORY[event]
    visible = category in _VISIBLE_CATEGORIES
    return NotificationState(
        visible=visible,
        category=category,
        buffer_count=buffer_count,
        label=_LABELS[category],
        message=_MESSAGES[category],
    )


def event_from_status(
    *,
    outcome: SubmitOutcome | None = None,
    http_status: int | None = None,
    timed_out: bool = False,
    network_error: bool = False,
    evicted: bool = False,
    configured: bool = True,
) -> NotificationEvent:
    """Map a concrete submission result to a :class:`NotificationEvent`.

    A convenience for callers (the client / GUI binding) that have an HTTP
    status, transport error, eviction signal, or configuration state rather
    than a pre-classified event. Precedence matches the design's notification
    semantics: an eviction (permanent drop) and a missing configuration are
    surfaced ahead of transport/status classification.

    Args:
        outcome: The mapped :class:`SubmitOutcome`, if available. ``PUBLISHED``
            and ``DUPLICATE`` are treated as success.
        http_status: The HTTP status code of the attempt, if one was received.
        timed_out: Whether the attempt timed out (Req 9.1).
        network_error: Whether the attempt failed with a network error.
        evicted: Whether an eviction just occurred (buffer overflow; Req 9.7).
        configured: Whether the client is configured (``API_Base_URL`` and
            ``Client_Credential`` present). ``False`` -> not-configured (Req 7.6).

    Returns:
        The :class:`NotificationEvent` summarizing this result.
    """
    if not configured:
        return NotificationEvent.NOT_CONFIGURED
    if evicted:
        return NotificationEvent.EVICTION

    if outcome in (SubmitOutcome.PUBLISHED, SubmitOutcome.DUPLICATE):
        return NotificationEvent.SUCCESS

    if http_status in (401, 403):
        return NotificationEvent.AUTH
    if timed_out or network_error:
        return NotificationEvent.OUTAGE
    if http_status is not None and 500 <= http_status <= 599:
        return NotificationEvent.OUTAGE

    # A successful status with no overriding signal also clears the notice.
    if http_status is not None and 200 <= http_status < 300:
        return NotificationEvent.SUCCESS

    # Fall back to an outage so an unexpected failure never silently hides the
    # notification.
    return NotificationEvent.OUTAGE
