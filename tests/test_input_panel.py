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
    _BACKEND_REKOGNITION,
    _BACKEND_YOLO,
    _CONF_SLIDER_MAX,
    _CONF_SLIDER_MIN,
    _DETECT_INTERVAL_MAX,
    _DETECT_INTERVAL_MIN,
    _SOURCE_MODE_FILE,
    _SOURCE_MODE_STREAM,
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


# ---------------------------------------------------------------------------
# Input source mode + stream URL visibility (Requirements 11.4)
# ---------------------------------------------------------------------------


def test_source_mode_defaults_to_file_with_stream_field_hidden(panel):
    """The default source mode is file; the stream URL field stays hidden."""
    assert panel.source_mode_combo.currentText() == _SOURCE_MODE_FILE
    assert panel.stream_url_widget.isVisibleTo(panel) is False
    # File selection control is available in the default (file) mode.
    assert panel.select_button.isVisibleTo(panel) is True
    assert panel.select_button.isEnabled() is True


def test_stream_mode_reveals_url_field(panel):
    """Switching to stream mode reveals the stream URL field."""
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_STREAM)
    assert panel.stream_url_widget.isVisibleTo(panel) is True


def test_file_controls_disabled_in_stream_mode(panel):
    """In stream mode the file selection control is hidden and disabled."""
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_STREAM)
    assert panel.select_button.isVisibleTo(panel) is False
    assert panel.select_button.isEnabled() is False

    # Returning to file mode re-enables it.
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_FILE)
    assert panel.select_button.isVisibleTo(panel) is True
    assert panel.select_button.isEnabled() is True


# ---------------------------------------------------------------------------
# Detector backend default + AWS region visibility (Requirements 12.4)
# ---------------------------------------------------------------------------


def test_detector_backend_defaults_to_yolo_with_region_hidden(panel):
    """The default detector backend is local YOLO; the region field is hidden."""
    assert panel.detector_combo.currentText() == _BACKEND_YOLO
    assert panel.aws_region_widget.isVisibleTo(panel) is False


def test_rekognition_backend_reveals_aws_region(panel):
    """Selecting AWS Rekognition reveals the AWS region field."""
    panel.detector_combo.setCurrentText(_BACKEND_REKOGNITION)
    assert panel.aws_region_widget.isVisibleTo(panel) is True

    # Switching back to YOLO hides it again.
    panel.detector_combo.setCurrentText(_BACKEND_YOLO)
    assert panel.aws_region_widget.isVisibleTo(panel) is False


# ---------------------------------------------------------------------------
# Detection interval bounds / default (Requirements 13.2)
# ---------------------------------------------------------------------------


def test_detect_interval_bounds_and_default(panel):
    """The detection interval spinbox is bounded to [1, 60] and defaults to 1."""
    assert panel.detect_interval_spin.minimum() == _DETECT_INTERVAL_MIN == 1
    assert panel.detect_interval_spin.maximum() == _DETECT_INTERVAL_MAX == 60
    assert panel.detect_interval_spin.value() == 1


def test_rekognition_interval_recommendation_visible_only_for_rekognition(panel):
    """The 5–10 interval recommendation shows only for the Rekognition backend."""
    assert panel.rekognition_hint.isVisibleTo(panel) is False

    panel.detector_combo.setCurrentText(_BACKEND_REKOGNITION)
    assert panel.rekognition_hint.isVisibleTo(panel) is True
    hint = panel.rekognition_hint.text()
    assert "5" in hint and "10" in hint

    panel.detector_combo.setCurrentText(_BACKEND_YOLO)
    assert panel.rekognition_hint.isVisibleTo(panel) is False


# ---------------------------------------------------------------------------
# No-output toggle disables the output path selector (Requirements 15.4)
# ---------------------------------------------------------------------------


def test_no_output_toggle_disables_output_selectors(panel):
    """Enabling no-output disables the output path field and browse button."""
    # Enabled by default (no-output off).
    assert panel.no_output_toggle.isChecked() is False
    assert panel.output_path_edit.isEnabled() is True
    assert panel.output_browse_button.isEnabled() is True

    panel.no_output_toggle.setChecked(True)
    assert panel.output_path_edit.isEnabled() is False
    assert panel.output_browse_button.isEnabled() is False

    # Turning it back off re-enables the selectors.
    panel.no_output_toggle.setChecked(False)
    assert panel.output_path_edit.isEnabled() is True
    assert panel.output_browse_button.isEnabled() is True


# ---------------------------------------------------------------------------
# Privacy note under Rekognition + plate reading (Requirements 12.4)
# ---------------------------------------------------------------------------


def test_privacy_note_visible_only_for_rekognition_with_plate_reading(panel):
    """The privacy note shows only when Rekognition and OCR are both active."""
    # Default (YOLO, OCR off): hidden.
    assert panel.privacy_note.isVisibleTo(panel) is False

    # Rekognition alone (OCR off): still hidden.
    panel.detector_combo.setCurrentText(_BACKEND_REKOGNITION)
    assert panel.privacy_note.isVisibleTo(panel) is False

    # Rekognition + plate reading: visible.
    panel.ocr_toggle.setChecked(True)
    assert panel.privacy_note.isVisibleTo(panel) is True

    # OCR on but YOLO backend: hidden again.
    panel.detector_combo.setCurrentText(_BACKEND_YOLO)
    assert panel.privacy_note.isVisibleTo(panel) is False


# ---------------------------------------------------------------------------
# validate_before_start error cases (Requirements 11.4, 12.4)
# ---------------------------------------------------------------------------


def test_validate_before_start_passes_in_default_file_mode(panel):
    """File mode with the default backend has no start-blocking validation error."""
    assert panel.validate_before_start() is None


def test_validate_before_start_requires_stream_url(panel):
    """Stream mode with an empty URL returns a 'enter a stream URL' message."""
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_STREAM)
    panel.stream_url_edit.setText("")
    error = panel.validate_before_start()
    assert error is not None
    assert "stream url" in error.lower()


def test_validate_before_start_rejects_malformed_stream_url(panel):
    """Stream mode with an unsupported scheme is rejected with a scheme hint."""
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_STREAM)
    panel.stream_url_edit.setText("ftp://camera/stream")
    error = panel.validate_before_start()
    assert error is not None
    assert "rtsp://" in error.lower()


def test_validate_before_start_accepts_valid_stream_url(panel):
    """A well-formed stream URL passes validation."""
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_STREAM)
    panel.stream_url_edit.setText("rtsp://192.0.2.10:554/stream")
    assert panel.validate_before_start() is None


def test_validate_before_start_requires_aws_region_for_rekognition(panel):
    """Rekognition with a blank region returns an 'enter an AWS region' message."""
    panel.detector_combo.setCurrentText(_BACKEND_REKOGNITION)
    panel.aws_region_edit.setText("")
    error = panel.validate_before_start()
    assert error is not None
    assert "aws region" in error.lower()


def test_validate_before_start_accepts_rekognition_with_region(panel):
    """Rekognition with a non-empty region passes validation."""
    panel.detector_combo.setCurrentText(_BACKEND_REKOGNITION)
    panel.aws_region_edit.setText("us-west-2")
    assert panel.validate_before_start() is None
