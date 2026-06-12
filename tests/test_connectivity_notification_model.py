"""Unit tests for the Connectivity_Notification render model (no Qt required).

These cover the pure ``build_render_model`` projection that drives the GUI
surface (gui/connectivity_notification.py). The Qt widget behavior itself is
exercised by the dedicated UI tests (task 13.4); here we verify the visual
contract that the surface binds to: the Opus orange token paired with a text
label for every visible warning, a hidden surface when there is nothing to
report, and a live buffer count.

Validates: Requirements 9.4, 9.6 (the render contract the surface applies).
"""

from __future__ import annotations

import pytest

from lanesight_client.notification import (
    NotificationCategory,
    NotificationEvent,
    reduce_notification,
)

# Import the pure helpers without importing the Qt widget module path that
# would require PySide6. The module imports PySide6 at top level, so guard.
PySide6 = pytest.importorskip("PySide6")  # noqa: N816

from gui.connectivity_notification import (  # noqa: E402
    ATTENTION_COLOR,
    build_render_model,
)

# The Opus orange attention token from ui_guidelines §5.
OPUS_ORANGE = "#FF8200"


def test_attention_color_is_opus_orange() -> None:
    """The accent token is exactly the Opus orange #FF8200 (Req 9.4)."""
    assert ATTENTION_COLOR == OPUS_ORANGE


@pytest.mark.parametrize(
    "event",
    [
        NotificationEvent.OUTAGE,
        NotificationEvent.AUTH,
        NotificationEvent.NOT_CONFIGURED,
        NotificationEvent.EVICTION,
    ],
)
def test_visible_warnings_pair_orange_with_text_label(event: NotificationEvent) -> None:
    """Every visible warning uses #FF8200 paired with visible text (Req 9.4)."""
    state = reduce_notification(event, buffer_count=3)
    model = build_render_model(state)

    assert model.visible is True
    # Color present...
    assert model.color == OPUS_ORANGE
    # ...and never alone: a standalone "Warning" prefix plus category label and
    # message all carry text so the alert does not rely on color.
    assert model.warning_prefix.strip() != ""
    assert model.label.strip() != ""
    assert model.message.strip() != ""


@pytest.mark.parametrize(
    "category,event",
    [
        (NotificationCategory.OUTAGE, NotificationEvent.OUTAGE),
        (NotificationCategory.AUTH, NotificationEvent.AUTH),
    ],
)
def test_auth_label_distinct_from_outage_label(
    category: NotificationCategory, event: NotificationEvent
) -> None:
    """Auth copy is distinct from outage copy (Req 9.5 carried into render)."""
    outage = build_render_model(reduce_notification(NotificationEvent.OUTAGE, 0))
    auth = build_render_model(reduce_notification(NotificationEvent.AUTH, 0))
    assert auth.label != outage.label
    assert auth.message != outage.message


def test_buffer_count_present_while_visible() -> None:
    """The live Pending_Snapshot_Buffer count is shown while visible (Req 9.2)."""
    state = reduce_notification(NotificationEvent.OUTAGE, buffer_count=42)
    model = build_render_model(state)
    assert model.show_buffer is True
    assert "42" in model.buffer_text


def test_hidden_when_publishing_healthy() -> None:
    """A success/none state renders nothing (Req 9.3 — clear on resume)."""
    state = reduce_notification(NotificationEvent.SUCCESS, buffer_count=0)
    model = build_render_model(state)
    assert model.visible is False
    assert model.color == ""
    assert model.show_buffer is False
