"""UI tests for the Connectivity_Notification Qt surface (task 13.4).

These exercise the real :class:`gui.connectivity_notification.ConnectivityNotification`
``QFrame`` through the headless ``offscreen`` Qt platform (configured in
tests/conftest.py via ``QT_QPA_PLATFORM=offscreen``). They verify the visible
behavior the operator actually experiences when ``bind_state`` is driven by the
``reduce_notification`` state reducer:

- On an OUTAGE / AUTH failure the surface becomes visible and shows the Opus
  orange ``#FF8200`` treatment paired with a visible text label (Req 9.1, 9.4).
- On a SUCCESS the surface clears (becomes hidden), modeling "clears within 2s
  on recovery" (Req 9.3).
- The displayed Pending_Snapshot_Buffer count updates when a new state with a
  different count is bound (Req 9.2).
- Auth copy is distinct from outage copy (Req 9.5).
- A permanent-drop (eviction) state surfaces the permanent-drop messaging
  (Req 9.7).
- Orange is always paired with a non-empty text label, never color alone
  (Req 9.4).
- The surface never grabs modality/focus/mouse, so other views remain
  interactive (Req 9.6).

Timing note (Req 9.1, 9.2, 9.3, 9.7 "within 2s"): the surface re-renders
synchronously inside ``bind_state`` — there is no timer, animation, or event
loop between a state change and the visible result. The 2-second budget is
therefore met by construction, so these tests assert the visibility/content
*transition* rather than wall-clock time.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

from __future__ import annotations

import pytest

# The surface imports PySide6 at module load; skip cleanly if the bindings or
# an offscreen platform are unavailable in this environment.
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from gui.connectivity_notification import (  # noqa: E402
    ATTENTION_COLOR,
    ConnectivityNotification,
)
from lanesight_client.notification import (  # noqa: E402
    NotificationEvent,
    reduce_notification,
)

# The Opus orange attention token from ui_guidelines §5.
OPUS_ORANGE = "#FF8200"


def _label_texts(widget: ConnectivityNotification) -> list[str]:
    """Return the non-empty text of every QLabel currently in the surface."""
    return [
        label.text()
        for label in widget.findChildren(QLabel)
        if label.text().strip() != ""
    ]


def _bind(widget: ConnectivityNotification, event: NotificationEvent, count: int) -> None:
    """Drive the surface from the reducer the way the live client does."""
    widget.bind_state(reduce_notification(event, buffer_count=count))


@pytest.fixture()
def notification(qapp) -> ConnectivityNotification:
    """A fresh ConnectivityNotification surface on the offscreen platform."""
    widget = ConnectivityNotification()
    yield widget
    widget.deleteLater()


@pytest.mark.parametrize("event", [NotificationEvent.OUTAGE, NotificationEvent.AUTH])
def test_failure_state_shows_orange_treatment_with_text_label(
    notification: ConnectivityNotification, event: NotificationEvent
) -> None:
    """A failure state makes the surface visible with #FF8200 + text (Req 9.1, 9.4)."""
    _bind(notification, event, count=4)

    # Visible: isHidden() reflects the explicit visibility flag even though the
    # widget is never shown in a real window on the offscreen harness.
    assert notification.isHidden() is False

    # The accent token is the Opus orange and it is referenced in the applied
    # stylesheet (the left accent bar / warning label color).
    assert ATTENTION_COLOR == OPUS_ORANGE
    assert OPUS_ORANGE in notification.styleSheet()

    # Color is never alone: at least one visible, non-empty text label is shown.
    texts = _label_texts(notification)
    assert texts, "a visible warning must carry text, not color alone"
    assert any(t.strip() for t in texts)


def test_recovery_clears_the_surface(notification: ConnectivityNotification) -> None:
    """A SUCCESS state clears (hides) the surface — clears on recovery (Req 9.3)."""
    # First fail so the surface is visible...
    _bind(notification, NotificationEvent.OUTAGE, count=2)
    assert notification.isHidden() is False

    # ...then a success clears it synchronously (well within the 2s budget).
    _bind(notification, NotificationEvent.SUCCESS, count=0)
    assert notification.isHidden() is True


def test_buffer_count_updates_when_rebound(
    notification: ConnectivityNotification,
) -> None:
    """The displayed buffer count refreshes when a new count is bound (Req 9.2)."""
    _bind(notification, NotificationEvent.OUTAGE, count=5)
    assert any("5" in t for t in _label_texts(notification))

    # A subsequent state with a different count updates the visible text.
    _bind(notification, NotificationEvent.OUTAGE, count=17)
    texts = _label_texts(notification)
    assert any("17" in t for t in texts)
    # The stale count is no longer the displayed pending-buffer figure.
    assert not any("Pending" in t and "5" in t and "17" not in t for t in texts)


def test_auth_copy_distinct_from_outage_copy(
    notification: ConnectivityNotification,
) -> None:
    """Auth failure copy differs from outage copy (Req 9.5)."""
    _bind(notification, NotificationEvent.OUTAGE, count=1)
    outage_texts = set(_label_texts(notification))

    _bind(notification, NotificationEvent.AUTH, count=1)
    auth_texts = set(_label_texts(notification))

    # The two states must not render an identical set of label strings: the
    # auth category communicates an auth/authorization problem, not an outage.
    assert auth_texts != outage_texts
    assert auth_texts - outage_texts, "auth state must add distinct copy"


def test_permanent_drop_state_shows_drop_messaging(
    notification: ConnectivityNotification,
) -> None:
    """An eviction surfaces permanent-drop messaging (Req 9.7)."""
    _bind(notification, NotificationEvent.EVICTION, count=1000)

    assert notification.isHidden() is False
    combined = " ".join(_label_texts(notification)).lower()
    # The reducer's permanent-drop copy speaks to snapshots being dropped.
    assert "drop" in combined
    # And it is still rendered with the orange warning treatment + text.
    assert OPUS_ORANGE in notification.styleSheet()


@pytest.mark.parametrize(
    "event",
    [
        NotificationEvent.OUTAGE,
        NotificationEvent.AUTH,
        NotificationEvent.NOT_CONFIGURED,
        NotificationEvent.EVICTION,
    ],
)
def test_orange_always_paired_with_text(
    notification: ConnectivityNotification, event: NotificationEvent
) -> None:
    """Every visible warning pairs #FF8200 with a non-empty label (Req 9.4)."""
    _bind(notification, event, count=3)
    assert notification.isHidden() is False
    assert OPUS_ORANGE in notification.styleSheet()
    assert _label_texts(notification), "warning must never rely on color alone"


def test_surface_is_non_modal_and_non_blocking(
    notification: ConnectivityNotification,
) -> None:
    """The surface never blocks other views (Req 9.6).

    It is a plain inline QFrame: non-modal, takes no focus, and is transparent
    to mouse events so clicks pass through to whatever it overlays.
    """
    _bind(notification, NotificationEvent.OUTAGE, count=1)

    # Not a modal dialog and not application/window modal.
    assert notification.isModal() is False
    assert notification.windowModality() == Qt.WindowModality.NonModal
    # Never steals keyboard focus from the active view.
    assert notification.focusPolicy() == Qt.FocusPolicy.NoFocus
    # Clicks fall through to the view beneath it.
    assert notification.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
