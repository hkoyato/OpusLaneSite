"""Connectivity_Notification GUI surface for the Opus LaneSight desktop app.

This widget is the visible counterpart to the pure
``lanesight_client.notification`` state reducer (task 13.1). The reducer decides
*what* to say (category, label, message, live buffer count); this surface
decides *how* to show it, following the Opus UI guidelines warning treatment.

Design references: design.md "Connectivity_Notification (GUI surface)",
Requirements 9.4 and 9.6, and ui_guidelines §5 (status color system) / §14
(accessibility — never rely on color alone).

Key behaviors:

- **Bound to client state (Req 9.1–9.3, 9.5, 9.7):** call
  :meth:`ConnectivityNotification.bind_state` with the
  :class:`~lanesight_client.notification.NotificationState` produced by the
  reducer. The surface re-renders to match; when the state is not visible
  (publishing healthy/resumed) the banner hides itself.
- **Warning treatment (Req 9.4):** visible warnings use the Opus orange
  attention token ``#FF8200`` (see :data:`ATTENTION_COLOR`) paired with a
  visible text label ("Warning") plus the category label and message — color is
  never the only signal. The orange is applied as a left accent bar and to the
  bold label text, while body copy stays charcoal on a light card for contrast.
- **Live buffer count (Req 9.2):** while visible, the current
  ``Pending_Snapshot_Buffer`` count carried on the state is displayed and
  refreshes every time ``bind_state`` is called.
- **Non-blocking (Req 9.6):** this is a plain inline ``QFrame`` banner, not a
  modal dialog. It is never shown with ``exec()`` and never grabs the keyboard,
  mouse, or application modality, so the operator can keep interacting with the
  detection pipeline view and any other view while it is displayed. It is
  additionally marked transparent to mouse events so that, if hosted as an
  overlay on top of another view, clicks pass through to the view beneath.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.theme import BrandTheme
from lanesight_client.notification import NotificationCategory, NotificationState

__all__ = [
    "ATTENTION_COLOR",
    "NotificationRenderModel",
    "build_render_model",
    "ConnectivityNotification",
]

# The Opus orange attention token (ui_guidelines §5). Sourced from the shared
# brand theme so there is a single source of truth for the value "#FF8200".
ATTENTION_COLOR: str = BrandTheme.ORANGE

# A short, always-visible text label that pairs with the orange treatment so
# the warning is never communicated by color alone (Req 9.4, ui_guidelines §14).
_WARNING_PREFIX = "Warning"


@dataclass(frozen=True)
class NotificationRenderModel:
    """Pure, framework-agnostic description of how to render the surface.

    Computed by :func:`build_render_model` from a
    :class:`~lanesight_client.notification.NotificationState`. Separating this
    from the Qt widget lets the rendering decisions be unit-tested without a
    running ``QApplication`` and keeps the visual contract explicit.

    Attributes:
        visible: Whether the banner should be shown at all.
        color: The accent color token. The Opus orange ``#FF8200`` for visible
            warnings, otherwise an empty string.
        warning_prefix: The standalone text label paired with the color so the
            warning never relies on color alone (e.g. ``"Warning"``). Empty when
            not visible.
        label: The category headline (e.g. "Publishing interrupted").
        message: The fuller explanatory copy for the category.
        buffer_text: Human-readable live buffer count line, shown while visible.
        show_buffer: Whether ``buffer_text`` should be displayed.
    """

    visible: bool
    color: str
    warning_prefix: str
    label: str
    message: str
    buffer_text: str
    show_buffer: bool


def build_render_model(state: NotificationState) -> NotificationRenderModel:
    """Derive the :class:`NotificationRenderModel` for a notification state.

    Pure and side-effect free. Visible warning states get the Opus orange
    attention token plus a "Warning" text label (never color alone, Req 9.4)
    and a live ``Pending_Snapshot_Buffer`` count line (Req 9.2). A non-visible
    state (publishing healthy/resumed) renders nothing.

    Args:
        state: The reducer-produced notification state to render.

    Returns:
        The render model the GUI surface (or any other toolkit) should apply.
    """
    if not state.visible or state.category is NotificationCategory.NONE:
        return NotificationRenderModel(
            visible=False,
            color="",
            warning_prefix="",
            label="",
            message="",
            buffer_text="",
            show_buffer=False,
        )

    # Pending snapshot count is surfaced for every visible warning so the
    # operator can watch the backlog grow or drain (Req 9.2). Sentence-case
    # label per ui_guidelines §7.
    buffer_text = f"Pending snapshots awaiting publication: {state.buffer_count}"

    return NotificationRenderModel(
        visible=True,
        color=ATTENTION_COLOR,
        warning_prefix=_WARNING_PREFIX,
        label=state.label,
        message=state.message,
        buffer_text=buffer_text,
        show_buffer=True,
    )


class ConnectivityNotification(QFrame):
    """Inline, non-modal warning banner bound to the client notification state.

    Use :meth:`bind_state` to drive the surface from the
    ``Connectivity_Notification`` reducer output. The widget owns no client
    state of its own — it is a pure projection of whatever
    :class:`NotificationState` it was last given.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # QFrame needs WA_StyledBackground for background-color QSS to paint.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Never intercept interaction from the views around/under it (Req 9.6).
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._build_ui()
        # Start hidden; nothing to report until the client reports a failure.
        self.setVisible(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Standalone "Warning" text label paired with the orange treatment so
        # the alert is conveyed by text as well as color (Req 9.4, §14).
        self._warning_label = QLabel(_WARNING_PREFIX)
        self._warning_label.setProperty("role", "card-title")
        root.addWidget(self._warning_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)

        self._title_label = QLabel("")
        self._title_label.setProperty("role", "card-title")

        self._message_label = QLabel("")
        self._message_label.setProperty("role", "body")
        self._message_label.setWordWrap(True)

        self._buffer_label = QLabel("")
        self._buffer_label.setProperty("role", "caption")
        self._buffer_label.setVisible(False)

        text_column.addWidget(self._title_label)
        text_column.addWidget(self._message_label)
        text_column.addWidget(self._buffer_label)
        root.addLayout(text_column, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def bind_state(self, state: NotificationState) -> None:
        """Render *state* onto the surface (Req 9.1–9.5, 9.7).

        Hides the banner when the state is not visible (publishing healthy or
        resumed, Req 9.3); otherwise shows the orange warning treatment with the
        category label, message, and the live ``Pending_Snapshot_Buffer`` count
        (Req 9.2). The same state always produces the same visual result.

        Args:
            state: The notification state produced by ``reduce_notification``.
        """
        model = build_render_model(state)
        self.apply_render_model(model)

    def apply_render_model(self, model: NotificationRenderModel) -> None:
        """Apply a precomputed :class:`NotificationRenderModel` to the widgets.

        Separated from :meth:`bind_state` so callers (and tests) can drive the
        surface directly from a render model if they already have one.
        """
        if not model.visible:
            self.setVisible(False)
            return

        # Orange left-accent bar + bold orange "Warning" label, charcoal body
        # copy on a light card for contrast (ui_guidelines §5 status-attention).
        self.setStyleSheet(
            f"background-color: {BrandTheme.WHITE}; "
            f"border: 1px solid {BrandTheme.CARD_BORDER}; "
            f"border-left: 5px solid {model.color}; "
            f"border-radius: 14px;"
        )
        self._warning_label.setText(model.warning_prefix)
        self._warning_label.setStyleSheet(
            f"color: {model.color}; font-weight: 700;"
        )

        self._title_label.setText(model.label)
        self._message_label.setText(model.message)

        self._buffer_label.setText(model.buffer_text)
        self._buffer_label.setVisible(model.show_buffer)

        self.setVisible(True)
