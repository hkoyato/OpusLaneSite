"""Unit tests for gui.station_controller.StationController.

Covers the controller's fallback and warning paths (station-identification spec):

  - Default applied when the Config_Store is empty/absent (Req 3.3).
  - Unreadable/corrupt store -> default applied + non-blocking warning (Req 3.4).
  - Read-only store -> set_active retains the config in memory for the session
    and a non-blocking warning is emitted (Req 3.6).
  - Active config is set at construction, before any producers run (Req 3.2).
  - Invalid persisted identifier -> default applied + warning (Req 3.5 example).

The Config_Store is isolated by monkeypatching ``SettingsManager.CONFIG_DIR``
and ``CONFIG_FILE`` onto a pytest ``tmp_path`` (same pattern as test_settings.py),
so no writes ever reach the real %LOCALAPPDATA% directory.

The repository does not use pytest-qt, so Qt signals are captured by connecting a
plain Python callable (``list.append``). The controller emits its load-time
warnings (Req 3.4 / 3.5) *during* ``__init__`` — before an external slot can be
connected — so ``_RecordingStationController`` connects a collector inside the
overridden ``_load_active`` (QObject.__init__ has already run at that point).

Reference: Requirements 3.2, 3.3, 3.4, 3.6 (and 3.5 example).
"""

from __future__ import annotations

import json

import pytest

from gui.models import StationConfig
from gui.settings import SettingsManager
from gui.station_controller import StationController
from gui.station_validation import DEFAULT_STATION_IDENTIFIER


@pytest.fixture
def patched_config(monkeypatch, tmp_path):
    """Redirect SettingsManager storage to a temporary directory.

    Returns a tuple of (config_dir, config_file) Paths.
    """
    config_dir = tmp_path / "OpusLaneSight"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(SettingsManager, "CONFIG_FILE", config_file)
    return config_dir, config_file


class _RecordingStationController(StationController):
    """StationController that captures warnings emitted during construction.

    The base class emits its Req 3.4 / 3.5 load-time warnings inside
    ``_load_active`` (called from ``__init__``), before any external observer
    could connect. By the time ``_load_active`` runs, ``QObject.__init__`` has
    already executed, so the bound ``warning`` signal is connectable; we attach
    a collector before delegating to the base implementation.
    """

    def __init__(self, settings: SettingsManager) -> None:
        self.captured_warnings: list[str] = []
        super().__init__(settings)

    def _load_active(self) -> StationConfig:
        self.warning.connect(self.captured_warnings.append)
        return super()._load_active()


def _write_store(config_file, **payload) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Requirement 3.2 — active config set at construction, before producers run
# ---------------------------------------------------------------------------


def test_active_config_set_at_construction(qapp, patched_config):
    """active_identifier() returns a non-empty string immediately after
    construction, with no extra calls (Req 3.2)."""
    controller = StationController(SettingsManager())

    identifier = controller.active_identifier()
    assert isinstance(identifier, str)
    assert identifier != ""
    # The active StationConfig is a fully-formed value object at construction.
    assert isinstance(controller.active(), StationConfig)


# ---------------------------------------------------------------------------
# Requirement 3.3 — default applied when the store is empty/absent
# ---------------------------------------------------------------------------


def test_default_applied_when_store_absent(qapp, patched_config):
    """With no settings file, the active identifier is the default and the
    display name equals the default identifier (Req 3.3)."""
    _, config_file = patched_config
    assert not config_file.exists()

    controller = _RecordingStationController(SettingsManager())

    assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER
    assert controller.active().display_name == DEFAULT_STATION_IDENTIFIER
    # The empty-store path is silent (no warning).
    assert controller.captured_warnings == []


def test_default_applied_when_store_empty_object(qapp, patched_config):
    """An empty JSON object (no station fields) yields the default config
    silently (Req 3.3)."""
    _, config_file = patched_config
    _write_store(config_file)  # writes "{}"

    controller = _RecordingStationController(SettingsManager())

    assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER
    assert controller.active().display_name == DEFAULT_STATION_IDENTIFIER
    assert controller.captured_warnings == []


# ---------------------------------------------------------------------------
# Requirement 3.4 — unreadable/corrupt store -> default + warning
# ---------------------------------------------------------------------------


def test_unreadable_store_applies_default_and_warns(qapp, patched_config):
    """When the store cannot be read (read_only), the default is applied and a
    non-blocking warning is emitted at construction (Req 3.4)."""
    mgr = SettingsManager()
    # Simulate a store that could not be read/written at launch.
    mgr._write_failed = True

    controller = _RecordingStationController(mgr)

    assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER
    assert controller.captured_warnings
    assert any("could not be read" in w for w in controller.captured_warnings)


def test_corrupt_store_applies_default(qapp, patched_config):
    """Invalid JSON in the store recovers to defaults (SettingsManager) and the
    controller surfaces the default identifier (Req 3.4)."""
    _, config_file = patched_config
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{ not valid json", encoding="utf-8")

    controller = StationController(SettingsManager())

    assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER


# ---------------------------------------------------------------------------
# Requirement 3.6 — read-only store: in-memory retention + warning
# ---------------------------------------------------------------------------


def test_read_only_store_set_active_retains_in_memory_and_warns(
    qapp, patched_config
):
    """When the store is read-only, set_active keeps the new config in memory
    for the session and emits a non-blocking warning (Req 3.6)."""
    mgr = SettingsManager()
    controller = StationController(mgr)  # writable at construction

    received: list[str] = []
    controller.warning.connect(received.append)

    # The store becomes non-writable for the remainder of the session.
    mgr._write_failed = True

    new_config = StationConfig("lane_seven", "Lane Seven")
    changed = controller.set_active(new_config)

    # Config retained in memory and reflected by active()/active_identifier().
    assert changed is True
    assert controller.active() == new_config
    assert controller.active_identifier() == "lane_seven"
    # A non-blocking "cannot persist" warning was emitted.
    assert received
    assert any("cannot be persisted" in w for w in received)


# ---------------------------------------------------------------------------
# Requirement 3.5 (example) — invalid persisted identifier -> default + warning
# ---------------------------------------------------------------------------


def test_invalid_persisted_identifier_applies_default_and_warns(
    qapp, patched_config
):
    """A persisted station_id that fails Requirement 2 validation is replaced by
    the default identifier and a warning is emitted (Req 3.5)."""
    _, config_file = patched_config
    _write_store(
        config_file,
        station_id="BAD ID!!",
        station_display_name="Bad Station",
    )

    controller = _RecordingStationController(SettingsManager())

    assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER
    # The persisted (valid) display name is retained alongside the default id.
    assert controller.active().display_name == "Bad Station"
    assert controller.captured_warnings
    assert any("invalid" in w.lower() for w in controller.captured_warnings)
