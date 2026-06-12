"""Integration tests for the Station Identification launch and save-reload flow.

Verifies the end-to-end wiring described in the station-identification design
("Testing Strategy" -> "Launch integration"):

  1. Construct a StationController from the Config_Store and assert producers can
     read a set, non-empty identifier BEFORE the first Report or Wait_Time_Output
     is produced (Req 3.2). The captured identifier flows into Vehicle_Session
     records, reports, and wait-time payloads.
  2. Save -> persist -> fresh reload yields the saved config (Req 3.1, 3.2): a
     value saved through one StationController is read back by a fresh
     SettingsManager/StationController over the same store.
  3. station_changed updates observers/header (Req 4.4): a plain Python collector
     connected to ``station_changed`` receives the effective display name when
     the active config changes, confirming the signal the header relies on fires
     synchronously on save.

The Config_Store is isolated by monkeypatching ``SettingsManager.CONFIG_DIR`` and
``CONFIG_FILE`` onto a pytest ``tmp_path`` (same pattern as
test_station_controller.py), so no writes ever reach the real %LOCALAPPDATA%.

The repository does not use pytest-qt; Qt signals are captured by connecting a
plain Python callable (``list.append``). The debounce Timer is flushed
synchronously via the ``_settle`` pattern (see test_station_properties.py /
test_station_controller.py) so persisted data is on disk before a fresh manager
reads it.

Reference: Requirements 3.1, 3.2, 4.4.
"""

from __future__ import annotations

import pytest

from gui.models import StationConfig
from gui.settings import SettingsManager
from gui.station_controller import StationController
from gui.station_records import build_vehicle_session
from gui.station_report import (
    REPORT_STATION_DISPLAY_NAME_FIELD,
    REPORT_STATION_ID_FIELD,
    build_report,
)
from gui.station_wait_time import (
    WAIT_TIME_STATION_DISPLAY_NAME_FIELD,
    WAIT_TIME_STATION_ID_FIELD,
    build_wait_time_output,
)


@pytest.fixture
def patched_config(monkeypatch, tmp_path):
    """Redirect SettingsManager storage to a temporary directory.

    Returns a tuple of (config_dir, config_file) Paths. Mirrors the isolation
    pattern in test_station_controller.py so no writes reach real %LOCALAPPDATA%.
    """
    config_dir = tmp_path / "OpusLaneSight"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(SettingsManager, "CONFIG_FILE", config_file)
    return config_dir, config_file


def _settle(manager: SettingsManager) -> None:
    """Cancel the pending debounce Timer and flush synchronously.

    SettingsManager.update() schedules a 0.5s Timer save; cancelling it prevents
    a late write firing after the temp store is torn down, and an explicit
    save() guarantees the data is on disk before a fresh manager reads it.
    """
    if manager._save_timer is not None:
        manager._save_timer.cancel()
    manager.save()


# ---------------------------------------------------------------------------
# 1. Producers read a set, non-empty identifier before the first output (Req 3.2)
# ---------------------------------------------------------------------------


def test_producers_read_active_identifier_before_first_output(qapp, patched_config):
    """Immediately after constructing the controller from the Config_Store, the
    active identifier is a non-empty string and feeds straight into the record,
    report, and wait-time producers (Req 3.2).

    No save or other call is made first: the active config is fully formed at
    construction, so producers running at launch already see a valid identifier.
    """
    controller = StationController(SettingsManager())

    # The active identifier is set and non-empty before any output is produced.
    identifier = controller.active_identifier()
    assert isinstance(identifier, str)
    assert identifier != ""

    # Vehicle_Session captures the identifier returned at creation (Req 5.1/3.2).
    session = build_vehicle_session({}, controller.active_identifier())
    assert session["station_id"] == identifier
    assert session["station_id"] != ""

    # Reports carry the active identity (Req 6.1, 6.2).
    report = build_report({"summary": "ok"}, controller.active())
    assert report[REPORT_STATION_ID_FIELD] == identifier
    assert (
        report[REPORT_STATION_DISPLAY_NAME_FIELD]
        == controller.active().effective_display_name
    )

    # Wait_Time_Output carries the active identity under fixed field names (Req 7).
    payload = build_wait_time_output({"wait_minutes": 5}, controller.active())
    assert payload[WAIT_TIME_STATION_ID_FIELD] == identifier
    assert (
        payload[WAIT_TIME_STATION_DISPLAY_NAME_FIELD]
        == controller.active().effective_display_name
    )


# ---------------------------------------------------------------------------
# 2. Save -> persist -> fresh reload yields the saved config (Req 3.1, 3.2)
# ---------------------------------------------------------------------------


def test_save_persist_reload_yields_saved_config(qapp, patched_config):
    """Saving a config through one controller and reconstructing a fresh
    SettingsManager/StationController over the same store yields the saved
    config (Req 3.1, 3.2)."""
    _, config_file = patched_config

    writer_manager = SettingsManager()
    writer = StationController(writer_manager)

    saved = StationConfig("lane_42", "Lane 42")
    writer.set_active(saved)
    # Force a synchronous write rather than relying on the debounce Timer.
    _settle(writer_manager)

    # The config reached disk.
    assert config_file.exists()

    # A fresh manager + controller over the same store reloads the saved config.
    reader_manager = SettingsManager()
    reader = StationController(reader_manager)
    try:
        assert reader.active() == saved
        assert reader.active_identifier() == "lane_42"
        assert reader.active().display_name == "Lane 42"
    finally:
        _settle(reader_manager)


# ---------------------------------------------------------------------------
# 3. station_changed updates observers / header (Req 4.4)
# ---------------------------------------------------------------------------


def test_station_changed_signal_updates_observers(qapp, patched_config):
    """Connecting a plain Python collector to ``station_changed`` and calling
    ``set_active`` delivers the effective display name synchronously (Req 4.4).

    This is the signal the MainWindow header relies on to refresh the active
    station label when the operator saves a new config.
    """
    manager = SettingsManager()
    controller = StationController(manager)

    received: list[str] = []
    controller.station_changed.connect(received.append)

    try:
        controller.set_active(StationConfig("lane_43", "Lane 43"))

        # The signal fired synchronously with the effective display name.
        assert received == ["Lane 43"]
    finally:
        _settle(manager)
