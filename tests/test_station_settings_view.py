"""Unit tests for :class:`gui.station_settings_view.StationSettingsView`.

Exercises the Station_Settings_View widget in isolation (station-identification
spec, Task 5.2):

  - The identifier/display-name fields and the "Save station" button exist with
    the correct max lengths (Req 1.1, 1.2, 1.3).
  - Fields are populated from the active config at construction and on showEvent
    (Req 1.4).
  - An invalid save shows an inline error and leaves the active config unchanged
    (Req 1.6, 2.3-2.7).
  - A changed valid save shows the confirmation and updates the active config
    (Req 1.6, 2.2).
  - The identifier field shows the full, untruncated identifier when it differs
    from the display name (Req 4.3).
  - The identifier field is empty when no active config is loaded (Req 4.5).

The Config_Store is isolated by monkeypatching ``SettingsManager.CONFIG_DIR`` and
``CONFIG_FILE`` onto a pytest ``tmp_path`` (same pattern as test_settings.py /
test_station_controller.py), so no writes ever reach the real %LOCALAPPDATA%.

The repository does not use pytest-qt; widgets are driven directly (call
``on_save_clicked()``, read ``.text()``, check ``.isHidden()`` /
``isVisibleTo()``). The view is never realized on screen, so visibility is
asserted via the explicit hidden flag (``isHidden()``) and ``isVisibleTo(view)``
rather than ``isVisible()`` (which is False for an unshown top-level widget).

Reference: Requirements 1.1, 1.2, 1.3, 1.4, 1.6, 2.2, 4.3, 4.5
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtGui import QShowEvent

from gui.models import StationConfig
from gui.settings import SettingsManager
from gui.station_controller import StationController
from gui.station_settings_view import StationSettingsView
from gui.station_validation import (
    DEFAULT_STATION_IDENTIFIER,
    DISPLAY_NAME_MAX_LEN,
    IDENTIFIER_MAX_LEN,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_config(monkeypatch, tmp_path):
    """Redirect SettingsManager storage to a temporary directory.

    Returns the (config_dir, config_file) Paths so individual tests can seed the
    store before constructing a controller.
    """
    config_dir = tmp_path / "OpusLaneSight"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(SettingsManager, "CONFIG_FILE", config_file)
    return config_dir, config_file


def _write_store(config_file, **payload) -> None:
    """Seed the Config_Store JSON with the given fields."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(payload), encoding="utf-8")


def _make_view(qapp, patched_config):
    """Construct a real StationController + StationSettingsView over a temp store."""
    controller = StationController(SettingsManager())
    view = StationSettingsView(controller)
    return controller, view


# ---------------------------------------------------------------------------
# Fields and button exist (Req 1.1, 1.2, 1.3)
# ---------------------------------------------------------------------------


def test_fields_and_save_button_exist(qapp, patched_config):
    """The identifier/display-name fields and the Save button are present."""
    _controller, view = _make_view(qapp, patched_config)

    # Identifier field (Req 1.1) and display-name field (Req 1.2) are QLineEdits.
    assert view.identifier_edit is not None
    assert view.display_name_edit is not None
    # Save control labelled "Save station" (Req 1.3).
    assert view.save_button is not None
    assert view.save_button.text() == "Save station"


def test_field_max_lengths(qapp, patched_config):
    """Identifier is capped at 64 chars (Req 1.1/4.3) and display name at 128 (Req 1.2)."""
    _controller, view = _make_view(qapp, patched_config)

    assert view.identifier_edit.maxLength() == IDENTIFIER_MAX_LEN == 64
    assert view.display_name_edit.maxLength() == DISPLAY_NAME_MAX_LEN == 128


# ---------------------------------------------------------------------------
# Fields populated on open (Req 1.4)
# ---------------------------------------------------------------------------


def test_fields_populated_from_active_at_construction(qapp, patched_config):
    """The view shows the active config's values immediately after construction."""
    _config_dir, config_file = patched_config
    _write_store(
        config_file,
        station_id="demo_station_07",
        station_display_name="Demo Inspection Station",
    )

    _controller, view = _make_view(qapp, patched_config)

    assert view.identifier_edit.text() == "demo_station_07"
    assert view.display_name_edit.text() == "Demo Inspection Station"


def test_fields_repopulated_on_show_event(qapp, patched_config):
    """showEvent re-populates the fields from the active config (Req 1.4)."""
    _config_dir, config_file = patched_config
    _write_store(
        config_file,
        station_id="demo_station_07",
        station_display_name="Demo Inspection Station",
    )

    _controller, view = _make_view(qapp, patched_config)

    # Simulate the operator having cleared the fields between opens.
    view.identifier_edit.setText("")
    view.display_name_edit.setText("")

    view.showEvent(QShowEvent())

    assert view.identifier_edit.text() == "demo_station_07"
    assert view.display_name_edit.text() == "Demo Inspection Station"


# ---------------------------------------------------------------------------
# Inline error on invalid save (Req 1.6, 2.3-2.7)
# ---------------------------------------------------------------------------


def test_invalid_identifier_save_shows_error_and_keeps_config(qapp, patched_config):
    """An illegal identifier is rejected: inline error shown, config unchanged."""
    controller, view = _make_view(qapp, patched_config)
    before = controller.active()

    view.identifier_edit.setText("BAD ID!!")
    view.display_name_edit.setText("Whatever")
    view.on_save_clicked()

    # Inline error visible with the allowed-charset message (Req 2.4).
    assert view.error_label.isHidden() is False
    assert "lowercase letters" in view.error_label.text().lower()
    # Active config retained unchanged (Req 2.3-2.5).
    assert controller.active() == before


def test_empty_identifier_save_shows_required_error_and_keeps_config(qapp, patched_config):
    """An empty identifier is rejected with the 'required' message (Req 2.3)."""
    controller, view = _make_view(qapp, patched_config)
    before = controller.active()

    view.identifier_edit.setText("")
    view.display_name_edit.setText("Demo Inspection Station")
    view.on_save_clicked()

    assert view.error_label.isHidden() is False
    assert "required" in view.error_label.text().lower()
    assert controller.active() == before


def test_overlong_display_name_save_shows_error_and_keeps_config(qapp, patched_config):
    """A display name > 128 chars is rejected with the 128-char message (Req 2.7)."""
    controller, view = _make_view(qapp, patched_config)
    before = controller.active()

    # The QLineEdit enforces a 128-char max, so raise it to drive the
    # validation path directly with a 129-character value.
    view.display_name_edit.setMaxLength(1000)
    view.identifier_edit.setText("valid_station")
    view.display_name_edit.setText("x" * 129)
    view.on_save_clicked()

    assert view.error_label.isHidden() is False
    assert view.error_label.text() == "Display name must be at most 128 characters."
    # Active config retained unchanged (Req 2.7).
    assert controller.active() == before


# ---------------------------------------------------------------------------
# Confirmation on changed save (Req 1.6, 2.2)
# ---------------------------------------------------------------------------


def test_changed_save_shows_confirmation_and_updates_config(qapp, patched_config):
    """A valid, differing save shows the confirmation and updates the active config."""
    controller, view = _make_view(qapp, patched_config)
    # Default active config is the default identifier for both fields.
    assert controller.active() == StationConfig(
        DEFAULT_STATION_IDENTIFIER, DEFAULT_STATION_IDENTIFIER
    )

    view.identifier_edit.setText("new_station_02")
    view.display_name_edit.setText("New Station")
    view.on_save_clicked()

    # Confirmation visible immediately (the 3s auto-hide timer does not fire
    # without an event loop), and no error shown.
    assert view.confirmation_label.isHidden() is False
    assert view.confirmation_label.text() == "Station configuration updated."
    assert view.error_label.isHidden() is True

    # Active config reflects the new values (Req 1.5, 2.2).
    assert controller.active() == StationConfig("new_station_02", "New Station")


# ---------------------------------------------------------------------------
# Distinct, non-truncated identifier when differing from display name (Req 4.3)
# ---------------------------------------------------------------------------


def test_identifier_field_shows_full_untruncated_value_when_differs(qapp, patched_config):
    """When identifier != display name, the identifier field shows the full value."""
    controller, view = _make_view(qapp, patched_config)

    # A maximum-length identifier (64 chars) distinct from the display name.
    long_identifier = "a" * IDENTIFIER_MAX_LEN
    controller.set_active(StationConfig(long_identifier, "Front Lane Station"))

    # The field is a distinct, visible widget (Req 4.3)...
    assert view.identifier_edit.isVisibleTo(view) is True
    # ...showing the complete, untruncated identifier.
    assert view.identifier_edit.text() == long_identifier
    assert len(view.identifier_edit.text()) == IDENTIFIER_MAX_LEN
    # The display name remains distinct from the identifier.
    assert view.display_name_edit.text() == "Front Lane Station"
    assert view.identifier_edit.text() != view.display_name_edit.text()


# ---------------------------------------------------------------------------
# Empty identifier field when no active config (Req 4.5)
# ---------------------------------------------------------------------------


def test_identifier_field_empty_when_no_active_config(qapp, patched_config, monkeypatch):
    """With no active config, the identifier field is left empty (Req 4.5)."""
    controller, view = _make_view(qapp, patched_config)

    # Simulate the controller reporting no active config.
    monkeypatch.setattr(controller, "active", lambda: None)
    view._populate_from_active()

    assert view.identifier_edit.text() == ""
    assert view.display_name_edit.text() == ""
