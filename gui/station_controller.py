"""StationController: single source of truth for the active StationConfig.

Holds the active :class:`StationConfig` in memory, loads/revalidates it from
the :class:`SettingsManager` (Config_Store) at construction so the active
config is set before any Report or Wait_Time_Output is produced (Req 3.2), and
notifies observers (the MainWindow header and the Station_Settings_View) via Qt
signals when it changes. Domain validation (Requirement 2) lives here, layered
on top of the SettingsManager's type/shape integrity, per the design.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from gui.models import StationConfig
from gui.settings import SettingsManager
from gui.station_validation import (
    DEFAULT_STATION_IDENTIFIER,
    IdentifierError,
    validate_display_name,
    validate_station_identifier,
)


class StationController(QObject):
    """Holds the active StationConfig and notifies observers on change.

    Construction loads and revalidates the persisted config from the
    SettingsManager (Config_Store) so the active config is set before any
    Report or Wait_Time_Output is produced (Req 3.2).
    """

    # Emitted whenever the active StationConfig changes. Payload is the
    # effective display name for header rendering (Req 4.1, 4.4).
    station_changed = Signal(str)
    # Emitted for non-blocking warnings (read error / invalid persisted id /
    # not writable) so MainWindow can show a toast (Req 3.4, 3.5, 3.6).
    warning = Signal(str)

    def __init__(self, settings: SettingsManager) -> None:
        super().__init__()
        self._settings = settings
        self._active: StationConfig = self._load_active()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def active(self) -> StationConfig:
        """Return the current active StationConfig (snapshot value object)."""
        return self._active

    def active_identifier(self) -> str:
        """Return the active Station_Identifier string captured at call time.

        Record producers call this at the moment a record is created (Req 5).
        """
        return self._active.identifier

    def set_active(self, config: StationConfig) -> bool:
        """Validate and set a new active config (used by the save path).

        Returns True when the config changed (so the view can show the
        'updated' confirmation, Req 1.6). Persists via SettingsManager and
        emits ``station_changed``; emits ``warning`` when the store is
        read-only after persisting (Req 3.6). Raises :class:`ValueError` on
        invalid input so the view can reject the save and keep the current
        config (Req 2.3-2.7).
        """
        id_error = validate_station_identifier(config.identifier)
        if id_error is not None:
            raise ValueError(self._identifier_error_message(id_error))
        if not validate_display_name(config.display_name):
            raise ValueError("Display name must be at most 128 characters.")

        changed = (
            config.identifier != self._active.identifier
            or config.display_name != self._active.display_name
        )

        self._active = config
        self._settings.update(
            station_id=config.identifier,
            station_display_name=config.display_name,
        )

        self.station_changed.emit(config.effective_display_name)

        if self._settings.read_only:
            self.warning.emit(
                "The station identifier cannot be persisted; it will be kept "
                "for this session only."
            )

        return changed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_active(self) -> StationConfig:
        """Read station fields from settings and revalidate the identifier.

          - no persisted config / equals defaults -> Default, silent (Req 3.3)
          - persisted id fails Requirement 2       -> Default + warning (Req 3.5)
          - otherwise                              -> persisted config (Req 3.2)

        The SettingsManager already falls back to default ``AppSettings`` on a
        missing or corrupt file and exposes ``read_only``; this method layers
        the identifier revalidation and default substitution on top (Req 3.4).
        """
        settings = self._settings.get()
        persisted_id = settings.station_id
        persisted_display = settings.station_display_name

        # The store could not be written/read at launch; surface a non-blocking
        # warning that the saved configuration could not be read (Req 3.4).
        if self._settings.read_only:
            self.warning.emit(
                "The saved station configuration could not be read; a default "
                "was applied."
            )

        if validate_station_identifier(persisted_id) is not None:
            # Persisted identifier is invalid: fall back to the default
            # identifier, keeping the persisted display name when present
            # (Req 3.5).
            self.warning.emit(
                "The saved station identifier was invalid; the default "
                "identifier was applied."
            )
            display = persisted_display or DEFAULT_STATION_IDENTIFIER
            return StationConfig(DEFAULT_STATION_IDENTIFIER, display)

        return StationConfig(persisted_id, persisted_display)

    @staticmethod
    def _identifier_error_message(error: IdentifierError) -> str:
        """Map an IdentifierError to its operator-facing message."""
        messages = {
            IdentifierError.EMPTY: "A station identifier is required.",
            IdentifierError.BAD_CHARSET: (
                "Use only lowercase letters, digits, hyphens, and underscores."
            ),
            IdentifierError.TOO_LONG: (
                "Station identifier must be at most 64 characters."
            ),
        }
        return messages[error]
