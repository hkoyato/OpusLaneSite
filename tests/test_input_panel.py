"""Unit tests for the InputPanel widget state (Task 6.2).

Verifies the InputPanel's interactive state transitions in isolation:
the start button gating on a valid video, OCR control visibility, the
confidence slider range/step mapping, and default output path derivation.

These tests run headless via the ``offscreen`` Qt platform (configured in
conftest.py) and never touch %LOCALAPPDATA%: a lightweight fake settings
object stands in for SettingsManager.

Validates: Requirements 2.4, 2.5, 2.6, 2.7, 2.8
"""

from __future__ import annotations

import pytest

from gui.input_panel import (
    _CONF_SLIDER_MAX,
    _CONF_SLIDER_MIN,
    InputPanel,
)
from gui.models import AppSettings, VideoMetadata
from gui.utils import derive_default_output_path


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSettings:
    """In-memory stand-in for SettingsManager.

    Exposes the two methods InputPanel relies on — ``get()`` returning an
    :class:`AppSettings` snapshot and ``update(**kwargs)`` mutating it — so
    tests never write to disk.
    """

    def __init__(self, **overrides: object) -> None:
        self._settings = AppSettings(**overrides)
        self.updates: list[dict] = []

    def get(self) -> AppSettings:
        return self._settings

    def update(self, **kwargs: object) -> None:
        self.updates.append(dict(kwargs))
        valid = {f.name for f in self._settings.__dataclass_fields__.values()}
        for key, value in kwargs.items():
            if key in valid:
                setattr(self._settings, key, value)


def _make_metadata(path: str) -> VideoMetadata:
    """Build a plausible VideoMetadata for *path* without opening a file."""
    return VideoMetadata(
        file_name=path.replace("\\", "/").rsplit("/", 1)[-1],
        file_path=path,
        width=1920,
        height=1080,
        frame_count=300,
        fps=30.0,
        duration_seconds=10.0,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def panel(qapp):
    """Construct an InputPanel backed by fake (in-memory) settings."""
    widget = InputPanel(FakeSettings())
    yield widget
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Start button gating (Requirements 2.4, 2.5)
# ---------------------------------------------------------------------------


def test_start_button_disabled_initially(panel):
    """With no video selected, the start button must be disabled."""
    assert panel.start_button.isEnabled() is False


def test_start_button_enabled_after_valid_video(panel, monkeypatch):
    """A valid video selection must enable the start button."""
    monkeypatch.setattr(
        panel, "validate_video", lambda p: _make_metadata(p)
    )

    panel.set_video_from_drop(r"C:\videos\clip.mp4")

    assert panel.start_button.isEnabled() is True
    assert panel.summary_card.isVisibleTo(panel) is True


def test_start_button_stays_disabled_for_invalid_video(panel, monkeypatch):
    """An unopenable file must leave the start button disabled and show an error."""
    monkeypatch.setattr(panel, "validate_video", lambda p: None)

    panel.set_video_from_drop(r"C:\videos\broken.mp4")

    assert panel.start_button.isEnabled() is False
    assert panel.error_label.isVisibleTo(panel) is True


# ---------------------------------------------------------------------------
# OCR control visibility (Requirement 2.6)
# ---------------------------------------------------------------------------


def test_ocr_settings_hidden_when_toggle_off(panel):
    """OCR settings are hidden by default (toggle off)."""
    assert panel.ocr_toggle.isChecked() is False
    assert panel.ocr_settings.isVisibleTo(panel) is False


def test_ocr_settings_visible_when_toggle_on(panel):
    """Enabling the OCR toggle reveals the OCR settings widget."""
    panel.ocr_toggle.setChecked(True)
    assert panel.ocr_settings.isVisibleTo(panel) is True

    # Toggling back off hides it again.
    panel.ocr_toggle.setChecked(False)
    assert panel.ocr_settings.isVisibleTo(panel) is False


# ---------------------------------------------------------------------------
# Confidence slider range and step (Requirement 2.8)
# ---------------------------------------------------------------------------


def test_confidence_slider_range_and_step(panel):
    """Slider is integer-backed over 2..20 with a single step of 1."""
    assert panel.confidence_slider.minimum() == _CONF_SLIDER_MIN == 2
    assert panel.confidence_slider.maximum() == _CONF_SLIDER_MAX == 20
    assert panel.confidence_slider.singleStep() == 1


def test_confidence_value_range_and_decimals(panel):
    """Numeric confidence entry covers 0.1..1.0 at 2 decimals, step 0.05."""
    assert panel.confidence_value.minimum() == pytest.approx(0.1)
    assert panel.confidence_value.maximum() == pytest.approx(1.0)
    assert panel.confidence_value.decimals() == 2
    assert panel.confidence_value.singleStep() == pytest.approx(0.05)


def test_confidence_slider_and_spin_stay_in_sync(panel):
    """Moving the slider updates the numeric value via the 0.05 mapping."""
    panel.confidence_slider.setValue(14)  # 14 * 0.05 = 0.70
    assert panel.confidence_value.value() == pytest.approx(0.70)

    panel.confidence_value.setValue(0.30)  # -> slider position 6
    assert panel.confidence_slider.value() == 6


# ---------------------------------------------------------------------------
# Default output path (Requirements 2.7)
# ---------------------------------------------------------------------------


def test_output_path_defaults_to_input_directory(panel, monkeypatch):
    """Selecting a video sets the default output path beside the input file."""
    path = r"C:\videos\station\clip.mp4"
    monkeypatch.setattr(
        panel, "validate_video", lambda p: _make_metadata(p)
    )

    panel.set_video_from_drop(path)

    assert panel.output_path_edit.text() == derive_default_output_path(path)


def test_output_path_not_overwritten_after_manual_override(panel, monkeypatch):
    """A user-chosen output path survives a subsequent video selection."""
    monkeypatch.setattr(
        panel, "validate_video", lambda p: _make_metadata(p)
    )

    # Simulate the user explicitly picking a custom output path.
    panel._output_overridden = True
    panel.output_path_edit.setText(r"D:\exports\custom.mp4")

    panel.set_video_from_drop(r"C:\videos\clip.mp4")

    assert panel.output_path_edit.text() == r"D:\exports\custom.mp4"
