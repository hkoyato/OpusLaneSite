"""Station_Settings_View: read and edit the active Station_Config.

Implements :class:`StationSettingsView`, the operator surface for viewing and
editing the Station_Identifier and Station_Display_Name (station-identification
spec). It validates input with the shared, Qt-free helpers in
:mod:`gui.station_validation`, delegates the active-config change to the
:class:`StationController` (the single source of truth), and surfaces inline
validation errors and a save/updated confirmation.

The widget communicates upward exclusively through the injected controller and
its ``station_changed`` signal, so it never references other view modules.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.models import StationConfig
from gui.station_controller import StationController
from gui.station_validation import (
    DISPLAY_NAME_MAX_LEN,
    IDENTIFIER_MAX_LEN,
    IdentifierError,
    validate_display_name,
    validate_station_identifier,
)

# BrandTheme is optional — the view degrades gracefully without it, matching
# the import-guard convention used by the other GUI views.
try:  # pragma: no cover - import guard
    from gui.theme import BrandTheme

    _ORANGE = BrandTheme.ORANGE
    _GRAY = BrandTheme.GRAY
    _GREEN = BrandTheme.GREEN
    _TEAL_DARK = BrandTheme.TEAL_DARK
except Exception:  # pragma: no cover - fallback colors
    BrandTheme = None  # type: ignore[assignment]
    _ORANGE = "#FF8200"
    _GRAY = "#54565A"
    _GREEN = "#93D500"
    _TEAL_DARK = "#004851"

# Inline validation messages keyed by IdentifierError (design message table).
_IDENTIFIER_ERROR_MESSAGES: dict[IdentifierError, str] = {
    IdentifierError.EMPTY: "A station identifier is required.",
    IdentifierError.BAD_CHARSET: (
        "Use only lowercase letters, digits, hyphens, and underscores."
    ),
    IdentifierError.TOO_LONG: "Station identifier must be at most 64 characters.",
}

# Display-name-too-long message (design message table).
_DISPLAY_NAME_TOO_LONG_MESSAGE = "Display name must be at most 128 characters."

# Confirmation auto-hide duration: at least 3 seconds (Req 1.6).
_CONFIRMATION_VISIBLE_MS = 3000


class StationSettingsView(QWidget):
    """Operator view for reading and editing the Station_Config."""

    def __init__(self, controller: StationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller

        self._build_ui()

        # Refresh the fields whenever the active config changes elsewhere
        # (for example, a default applied at launch or a future external edit).
        self._controller.station_changed.connect(self._on_station_changed)

        # Populate fields from the active config immediately so the view is
        # correct even before it is first shown.
        self._populate_from_active()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(24)

        title = QLabel("Station settings")
        title.setProperty("role", "section-title")
        root.addWidget(title)

        intro = QLabel(
            "Set the station this instance represents. The identifier is "
            "attached to every record and report; the display name is shown "
            "in the header and public surfaces."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "body")
        intro.setProperty("secondary", True)
        intro.setStyleSheet(f"color: {_GRAY};")
        root.addWidget(intro)

        root.addWidget(self._build_fields_card())

        # --- Inline validation error (orange, hidden until an error) -----
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {_ORANGE}; font-weight: 600;")
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        # --- Confirmation message / toast (hidden until a save) ----------
        self.confirmation_label = QLabel("")
        self.confirmation_label.setWordWrap(True)
        self.confirmation_label.setStyleSheet(
            f"color: {_TEAL_DARK}; font-weight: 600;"
        )
        self.confirmation_label.setVisible(False)
        root.addWidget(self.confirmation_label)

        root.addStretch(1)

        # --- Save action -------------------------------------------------
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton("Save station")
        self.save_button.clicked.connect(self.on_save_clicked)
        button_row.addWidget(self.save_button)
        root.addLayout(button_row)

        # Timer used to auto-hide the confirmation after >= 3s (Req 1.6). The
        # confirmation can also be dismissed manually via dismiss_confirmation.
        self._confirmation_timer = QTimer(self)
        self._confirmation_timer.setSingleShot(True)
        self._confirmation_timer.timeout.connect(self.dismiss_confirmation)

    def _build_fields_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        if BrandTheme is not None:
            card.setStyleSheet(BrandTheme.card_style())
        layout = QGridLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(16)

        heading = QLabel("Station identity")
        heading.setProperty("role", "card-title")
        layout.addWidget(heading, 0, 0, 1, 2)

        # --- Station identifier -----------------------------------------
        id_label = QLabel("Station identifier")
        id_label.setProperty("secondary", True)
        id_label.setStyleSheet(f"color: {_GRAY};")
        layout.addWidget(id_label, 1, 0)

        self.identifier_edit = QLineEdit()
        self.identifier_edit.setMaxLength(IDENTIFIER_MAX_LEN)  # Req 1.1, 4.3
        self.identifier_edit.setPlaceholderText("e.g. demo_station_01")
        self.identifier_edit.setToolTip(
            "1-64 characters: lowercase letters, digits, hyphens, underscores."
        )
        # Show the identifier as a distinct, non-truncated field (Req 4.3): a
        # single-line edit that scrolls rather than eliding, always visible.
        self.identifier_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.identifier_edit.textEdited.connect(self._on_field_edited)
        layout.addWidget(self.identifier_edit, 1, 1)

        # --- Station display name ---------------------------------------
        name_label = QLabel("Display name")
        name_label.setProperty("secondary", True)
        name_label.setStyleSheet(f"color: {_GRAY};")
        layout.addWidget(name_label, 2, 0)

        self.display_name_edit = QLineEdit()
        self.display_name_edit.setMaxLength(DISPLAY_NAME_MAX_LEN)  # Req 1.2
        self.display_name_edit.setPlaceholderText(
            "Optional human-readable label, e.g. Demo Inspection Station"
        )
        self.display_name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.display_name_edit.textEdited.connect(self._on_field_edited)
        layout.addWidget(self.display_name_edit, 2, 1)

        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        return card

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: ANN001 - Qt event
        """Populate fields from the active config on open (Req 1.4).

        Population is synchronous (well within the 2-second budget). When no
        active config is loaded, the identifier field is left empty (Req 4.5).
        """
        self._populate_from_active()
        super().showEvent(event)

    # ------------------------------------------------------------------
    # Save flow
    # ------------------------------------------------------------------

    def on_save_clicked(self) -> None:
        """Validate both fields and apply the change.

        On error, show the inline message and leave the active config
        unchanged (Req 2.3-2.7). On success, build a StationConfig, set it via
        the controller, and show the saved/updated confirmation kept visible
        for at least 3 seconds or until dismissed (Req 1.5, 1.6, 2.2).
        """
        identifier = self.identifier_edit.text()
        display_name = self.display_name_edit.text()

        # Validate identifier first, then display name, using the shared rules.
        id_error = validate_station_identifier(identifier)
        if id_error is not None:
            self._show_error(_IDENTIFIER_ERROR_MESSAGES[id_error])
            return  # active config unchanged (Req 2.3-2.5)

        if not validate_display_name(display_name):
            self._show_error(_DISPLAY_NAME_TOO_LONG_MESSAGE)
            return  # active config unchanged (Req 2.7)

        config = StationConfig(identifier, display_name)

        # The controller re-validates as a safety net; guard against a
        # ValueError so a race with external state can never crash the save.
        try:
            changed = self._controller.set_active(config)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self._clear_error()
        # "updated" when the resulting config differs (Req 1.6); otherwise the
        # save succeeded with no change, confirmed as "saved" (Req 2.2).
        if changed:
            self._show_confirmation("Station configuration updated.")
        else:
            self._show_confirmation("Station configuration saved.")

    # ------------------------------------------------------------------
    # Confirmation / error helpers
    # ------------------------------------------------------------------

    def _show_error(self, message: str) -> None:
        # An error supersedes any visible confirmation.
        self.dismiss_confirmation()
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _show_confirmation(self, message: str) -> None:
        self.confirmation_label.setText(message)
        self.confirmation_label.setVisible(True)
        # Keep it visible for at least 3 seconds (Req 1.6).
        self._confirmation_timer.start(_CONFIRMATION_VISIBLE_MS)

    def dismiss_confirmation(self) -> None:
        """Hide the confirmation message (manual or timed dismissal, Req 1.6)."""
        self._confirmation_timer.stop()
        self.confirmation_label.clear()
        self.confirmation_label.setVisible(False)

    def _on_field_edited(self, _text: str) -> None:
        # Clear a stale inline error as the operator corrects the input.
        if self.error_label.isVisible():
            self._clear_error()

    # ------------------------------------------------------------------
    # Active-config population
    # ------------------------------------------------------------------

    def _on_station_changed(self, _display_name: str) -> None:
        """Refresh fields when the active config changes (controller signal)."""
        self._populate_from_active()

    def _populate_from_active(self) -> None:
        """Load the active StationConfig into the editable fields (Req 1.4).

        When no active config is loaded, the identifier field is left empty
        (Req 4.5).
        """
        config = self._controller.active()
        if config is None:
            self.identifier_edit.setText("")
            self.display_name_edit.setText("")
            return
        self.identifier_edit.setText(config.identifier)
        self.display_name_edit.setText(config.display_name)
