"""Unit tests for gui.settings.SettingsManager.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5

Each test monkeypatches both ``CONFIG_DIR`` and ``CONFIG_FILE`` class
attributes onto a pytest ``tmp_path`` so no writes ever reach the real
%LOCALAPPDATA% directory. Saves are triggered explicitly via ``save()`` for
deterministic behaviour (``update()`` schedules a 0.5s debounce Timer which we
avoid relying on).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gui.models import AppSettings
from gui.settings import SettingsManager


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


# ---------------------------------------------------------------------------
# Requirement 5.1 — directory creation when missing
# ---------------------------------------------------------------------------


def test_save_creates_directory_and_file_when_missing(patched_config):
    """save() creates CONFIG_DIR and CONFIG_FILE when they do not exist."""
    config_dir, config_file = patched_config
    assert not config_dir.exists()

    mgr = SettingsManager()
    mgr.save()

    assert config_dir.exists()
    assert config_file.exists()
    # File contains valid JSON
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert mgr.read_only is False


# ---------------------------------------------------------------------------
# Requirement 5.2 — default values applied on first launch
# ---------------------------------------------------------------------------


def test_defaults_applied_on_first_launch(patched_config):
    """With no settings file present, get() returns AppSettings() defaults."""
    config_dir, config_file = patched_config
    assert not config_file.exists()

    settings = SettingsManager().get()

    assert settings == AppSettings()
    # Explicit checks of the documented defaults
    assert settings.confidence == 0.5
    assert settings.ocr_enabled is False
    assert settings.ocr_language == "en"
    assert settings.ocr_interval == 10


# ---------------------------------------------------------------------------
# Requirement 5.3 — corrupt file recovery
# ---------------------------------------------------------------------------


def test_corrupt_file_recovers_to_defaults(patched_config):
    """Invalid JSON in the settings file yields AppSettings() defaults."""
    config_dir, config_file = patched_config
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{ not json", encoding="utf-8")

    mgr = SettingsManager()

    assert mgr.get() == AppSettings()


def test_corrupt_file_overwritten_with_valid_json_on_save(patched_config):
    """After recovering from corrupt JSON, save() writes valid JSON."""
    config_dir, config_file = patched_config
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{ not json", encoding="utf-8")

    mgr = SettingsManager()
    mgr.save()

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["confidence"] == 0.5
    assert data["ocr_language"] == "en"


def test_non_dict_json_recovers_to_defaults(patched_config):
    """A JSON array (not an object) is treated as invalid -> defaults."""
    config_dir, config_file = patched_config
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text("[1, 2, 3]", encoding="utf-8")

    assert SettingsManager().get() == AppSettings()


# ---------------------------------------------------------------------------
# Requirement 5.4 — value clamping for out-of-range values
# ---------------------------------------------------------------------------


def _write_settings(config_file: Path, **overrides) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(overrides), encoding="utf-8")


def test_high_out_of_range_values_clamped_on_load(patched_config):
    """confidence=5.0 -> 1.0, ocr_interval=999 -> 100 on load."""
    _, config_file = patched_config
    _write_settings(config_file, confidence=5.0, ocr_interval=999)

    settings = SettingsManager().get()

    assert settings.confidence == 1.0
    assert settings.ocr_interval == 100


def test_low_out_of_range_values_clamped_on_load(patched_config):
    """confidence=-1 -> 0.1, ocr_interval=0 -> 1 on load."""
    _, config_file = patched_config
    _write_settings(config_file, confidence=-1, ocr_interval=0)

    settings = SettingsManager().get()

    assert settings.confidence == 0.1
    assert settings.ocr_interval == 1


def test_update_clamps_out_of_range_confidence(patched_config):
    """update(confidence=2.0) re-validates and clamps to 1.0."""
    mgr = SettingsManager()

    mgr.update(confidence=2.0)

    assert mgr.get().confidence == 1.0


def test_update_clamps_out_of_range_interval(patched_config):
    """update(ocr_interval=999) clamps to 100; 0 clamps to 1."""
    mgr = SettingsManager()

    mgr.update(ocr_interval=999)
    assert mgr.get().ocr_interval == 100

    mgr.update(ocr_interval=0)
    assert mgr.get().ocr_interval == 1


def test_clamped_values_round_trip_through_save_and_reload(patched_config):
    """Clamped values persist and reload identically."""
    _, config_file = patched_config
    _write_settings(config_file, confidence=5.0, ocr_interval=999)

    SettingsManager().save()  # rewrite clamped values
    reloaded = SettingsManager().get()

    assert reloaded.confidence == 1.0
    assert reloaded.ocr_interval == 100


# ---------------------------------------------------------------------------
# Requirement 5.5 — read-only / in-memory fallback when not writable
# ---------------------------------------------------------------------------


def test_read_only_flag_set_when_directory_creation_fails(patched_config, monkeypatch):
    """If mkdir raises OSError, save() sets read_only without raising."""
    def _raise_mkdir(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", _raise_mkdir)

    mgr = SettingsManager()
    mgr.save()  # must not raise

    assert mgr.read_only is True


def test_read_only_flag_set_when_file_write_fails(patched_config, monkeypatch):
    """If write_text raises OSError, save() sets read_only without raising."""
    def _raise_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _raise_write)

    mgr = SettingsManager()
    mgr.save()  # must not raise

    assert mgr.read_only is True
    # In-memory settings still usable
    assert mgr.get() == AppSettings()


def test_read_only_false_after_successful_save(patched_config):
    """read_only is False on a normal successful save."""
    mgr = SettingsManager()
    mgr.save()
    assert mgr.read_only is False
