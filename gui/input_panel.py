"""Video input selection and processing parameter configuration view.

Implements the :class:`InputPanel` widget: file selection, video metadata
display, detection/OCR parameter controls, output path selection, and the
"Start processing" action. Communicates upward exclusively through the
``start_requested`` signal so it never references other view modules.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.models import ProcessingConfig, VideoMetadata
from gui.settings import SettingsManager
from gui.utils import (
    clamp_confidence,
    derive_default_output_path,
    is_valid_aws_region,
    is_valid_stream_url,
)

# BrandTheme is optional — the panel degrades gracefully without it.
try:  # pragma: no cover - import guard
    from gui.theme import BrandTheme

    _ORANGE = BrandTheme.ORANGE
    _GRAY = BrandTheme.GRAY
    _TEAL_DARK = BrandTheme.TEAL_DARK
except Exception:  # pragma: no cover - fallback colors
    BrandTheme = None  # type: ignore[assignment]
    _ORANGE = "#FF8200"
    _GRAY = "#54565A"
    _TEAL_DARK = "#004851"


# Confidence slider is integer-backed. One step == 0.05; the slider range
# 2..20 maps to confidence 0.10..1.00 (default 10 -> 0.50).
_CONF_STEP = 0.05
_CONF_SLIDER_MIN = 2
_CONF_SLIDER_MAX = 20

# Native file dialog filter for accepted video container formats.
_VIDEO_FILTER = "Video files (*.mp4 *.avi *.mov *.mkv);;All files (*)"

# OCR language options offered in the dropdown.
_OCR_LANGUAGES = ["en", "es", "fr", "de", "it", "pt"]

# Input source mode options (Req 11.1). Display text -> internal value.
_SOURCE_MODE_FILE = "Video file"
_SOURCE_MODE_STREAM = "Live stream"

# Detector backend options (Req 12.1). Display text -> internal value.
_BACKEND_YOLO = "Local YOLOv8"
_BACKEND_REKOGNITION = "AWS Rekognition"

# Field length limits mirrored from the validators in gui.utils.
_MAX_STREAM_URL_LENGTH = 2048
_MAX_AWS_REGION_LENGTH = 64

# Detection interval bounds (Req 13.1).
_DETECT_INTERVAL_MIN = 1
_DETECT_INTERVAL_MAX = 60

# Active-lanes (manual station override) bounds.
_ACTIVE_LANES_MIN = 1
_ACTIVE_LANES_MAX = 99

# Privacy note shown for Rekognition + plate reading (Req 12.9 / Req 1.5).
_PRIVACY_NOTE = (
    "Plate text reading is opt-in and used for development and testing only. "
    "LaneSight uses temporary anonymous vehicle session IDs and does not read "
    "or store license plates or driver identities."
)

# Recommendation shown for the Rekognition backend (Req 13.3).
_REKOGNITION_INTERVAL_HINT = (
    "Recommended detection interval for AWS Rekognition is 5\u201310 to reduce "
    "API calls and cost."
)


def _safe_row_height(label: QLabel) -> int:
    """A minimum label height that never clips glyphs.

    Some environments (notably when Qt cannot locate a real font) report a
    degenerate line height with zero descent, which clips descenders. Pad the
    natural line spacing so text always renders fully.
    """
    fm = label.fontMetrics()
    return max(fm.lineSpacing(), fm.height()) + 6


class _ElidingLabel(QLabel):
    """Single-line label that middle-elides its text to the available width.

    Keeps the full text available via :meth:`text` and as a tooltip, so long
    values (such as file paths) display as much as fits without ever wrapping
    inside a grid layout (which is where word-wrapped labels get clipped).
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        if text:
            self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def text(self) -> str:  # noqa: N802 - Qt override
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt event
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(0, self.width())
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, width
        )
        super().setText(elided)


def _conf_to_slider(value: float) -> int:
    """Map a confidence value in [0.1, 1.0] to the integer slider position."""
    return int(round(value / _CONF_STEP))


def _slider_to_conf(position: int) -> float:
    """Map an integer slider position to a confidence value (2 decimals)."""
    return round(position * _CONF_STEP, 2)


class InputPanel(QWidget):
    """Video input selection and processing parameter configuration."""

    # Emitted with a fully-populated ProcessingConfig when the user starts.
    start_requested = Signal(ProcessingConfig)

    def __init__(self, settings: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._metadata: VideoMetadata | None = None
        # True while we apply persisted values, to suppress save feedback loops.
        self._loading = False
        # True once the user explicitly picks an output path via the browser,
        # so selecting a new video does not silently overwrite their choice.
        self._output_overridden = False

        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(24)

        title = QLabel("Select input video")
        title.setProperty("role", "section-title")
        root.addWidget(title)

        # --- Input source mode selector (Req 11.1) ----------------------
        source_row = QHBoxLayout()
        source_row.setSpacing(12)
        source_label = QLabel("Input source")
        source_label.setMinimumWidth(180)
        source_row.addWidget(source_label)
        self.source_mode_combo = QComboBox()
        self.source_mode_combo.addItems([_SOURCE_MODE_FILE, _SOURCE_MODE_STREAM])
        self.source_mode_combo.setCurrentText(_SOURCE_MODE_FILE)
        self.source_mode_combo.currentTextChanged.connect(self.on_source_mode_changed)
        source_row.addWidget(self.source_mode_combo)
        source_row.addStretch(1)
        root.addLayout(source_row)

        # --- File selection row -----------------------------------------
        file_row = QHBoxLayout()
        file_row.setSpacing(12)
        self.select_button = QPushButton("Choose video file")
        self.select_button.clicked.connect(self.select_video_file)
        file_row.addWidget(self.select_button)
        file_row.addStretch(1)
        root.addLayout(file_row)

        # --- Stream URL field (shown only in stream mode, Req 11.2) ------
        self.stream_url_widget = QWidget()
        stream_layout = QHBoxLayout(self.stream_url_widget)
        stream_layout.setContentsMargins(0, 0, 0, 0)
        stream_layout.setSpacing(12)
        stream_label = QLabel("Stream URL")
        stream_label.setMinimumWidth(180)
        stream_layout.addWidget(stream_label)
        self.stream_url_edit = QLineEdit()
        self.stream_url_edit.setMaxLength(_MAX_STREAM_URL_LENGTH)
        self.stream_url_edit.setPlaceholderText(
            "rtsp://, rtmp://, http:// or https:// stream URL"
        )
        self.stream_url_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.stream_url_edit.textChanged.connect(self._on_stream_url_changed)
        stream_layout.addWidget(self.stream_url_edit, 1)
        self.stream_url_widget.setVisible(False)
        root.addWidget(self.stream_url_widget)

        # --- Inline error message ---------------------------------------
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {_ORANGE}; font-weight: 600;")
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        # --- Metadata summary card --------------------------------------
        self.summary_card = self._build_summary_card()
        self.summary_card.setVisible(False)
        root.addWidget(self.summary_card)

        # --- Parameter controls card ------------------------------------
        root.addWidget(self._build_parameters_card())

        root.addStretch(1)

        # --- Start button -----------------------------------------------
        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_button = QPushButton("Start processing")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        root.addLayout(start_row)

    def _build_summary_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        layout = QGridLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(8)

        heading = QLabel("Video details")
        heading.setProperty("role", "card-title")
        layout.addWidget(heading, 0, 0, 1, 2)

        # Value labels, populated on selection.
        self._meta_values: dict[str, QLabel] = {}
        rows = [
            ("file_name", "File name"),
            ("file_path", "Path"),
            ("resolution", "Resolution"),
            ("frame_count", "Frame count"),
            ("duration", "Duration"),
            ("fps", "FPS"),
        ]
        for idx, (key, label_text) in enumerate(rows, start=1):
            key_label = QLabel(label_text)
            key_label.setProperty("secondary", True)
            key_label.setWordWrap(False)
            key_label.setStyleSheet(f"color: {_GRAY};")
            key_label.setMinimumHeight(_safe_row_height(key_label))

            # The path can be very long; elide it (full value in tooltip).
            # All values are single-line to avoid grid word-wrap clipping.
            if key == "file_path":
                value_label: QLabel = _ElidingLabel("—")
            else:
                value_label = QLabel("—")
                value_label.setWordWrap(False)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setMinimumHeight(_safe_row_height(value_label))

            layout.addWidget(key_label, idx, 0)
            layout.addWidget(value_label, idx, 1)
            self._meta_values[key] = value_label

        # Let the value column take the remaining width so values render fully.
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)

        return card

    def _build_parameters_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        heading = QLabel("Processing parameters")
        heading.setProperty("role", "card-title")
        layout.addWidget(heading)

        # --- Confidence threshold ---------------------------------------
        conf_row = QHBoxLayout()
        conf_row.setSpacing(12)
        conf_label = QLabel("Detection confidence")
        conf_label.setMinimumWidth(180)
        conf_row.addWidget(conf_label)

        self.confidence_slider = QSlider(Qt.Horizontal)
        self.confidence_slider.setRange(_CONF_SLIDER_MIN, _CONF_SLIDER_MAX)
        self.confidence_slider.setSingleStep(1)
        self.confidence_slider.setPageStep(1)
        self.confidence_slider.setValue(_conf_to_slider(0.5))
        self.confidence_slider.valueChanged.connect(self._on_slider_changed)
        conf_row.addWidget(self.confidence_slider, 1)

        # Numeric display + manual entry (2 decimal places).
        self.confidence_value = QDoubleSpinBox()
        self.confidence_value.setRange(0.1, 1.0)
        self.confidence_value.setSingleStep(_CONF_STEP)
        self.confidence_value.setDecimals(2)
        self.confidence_value.setValue(0.5)
        self.confidence_value.setToolTip("Valid range is 0.1 to 1.0.")
        self.confidence_value.valueChanged.connect(self._on_confidence_spin_changed)
        self.confidence_value.editingFinished.connect(self._on_confidence_entry_finished)
        conf_row.addWidget(self.confidence_value)
        layout.addLayout(conf_row)

        # --- OCR toggle --------------------------------------------------
        self.ocr_toggle = QCheckBox("Enable OCR (plate text reading)")
        self.ocr_toggle.setToolTip(
            "OCR reads license plate text for development and testing purposes "
            "only. Leave disabled for the privacy-preserving demo."
        )
        self.ocr_toggle.toggled.connect(self._on_ocr_toggled)
        layout.addWidget(self.ocr_toggle)

        # --- OCR settings (shown only when OCR enabled) ------------------
        self.ocr_settings = QWidget()
        ocr_layout = QHBoxLayout(self.ocr_settings)
        ocr_layout.setContentsMargins(24, 0, 0, 0)
        ocr_layout.setSpacing(12)

        ocr_layout.addWidget(QLabel("Language"))
        self.ocr_language = QComboBox()
        self.ocr_language.addItems(_OCR_LANGUAGES)
        self.ocr_language.setCurrentText("en")
        self.ocr_language.currentTextChanged.connect(self._on_ocr_language_changed)
        ocr_layout.addWidget(self.ocr_language)

        ocr_layout.addSpacing(16)
        ocr_layout.addWidget(QLabel("Frame interval"))
        self.ocr_interval = QSpinBox()
        self.ocr_interval.setRange(1, 100)
        self.ocr_interval.setValue(10)
        self.ocr_interval.setToolTip("Run OCR every N frames (1–100).")
        self.ocr_interval.valueChanged.connect(self._on_ocr_interval_changed)
        ocr_layout.addWidget(self.ocr_interval)
        ocr_layout.addStretch(1)

        self.ocr_settings.setVisible(False)
        layout.addWidget(self.ocr_settings)

        # --- Detector backend selector (Req 12.1) -----------------------
        backend_row = QHBoxLayout()
        backend_row.setSpacing(12)
        backend_label = QLabel("Detector backend")
        backend_label.setMinimumWidth(180)
        backend_row.addWidget(backend_label)
        self.detector_combo = QComboBox()
        self.detector_combo.addItems([_BACKEND_YOLO, _BACKEND_REKOGNITION])
        self.detector_combo.setCurrentText(_BACKEND_YOLO)
        self.detector_combo.currentTextChanged.connect(self.on_detector_backend_changed)
        backend_row.addWidget(self.detector_combo)
        backend_row.addStretch(1)
        layout.addLayout(backend_row)

        # --- AWS region field (shown only for Rekognition, Req 12.2) -----
        self.aws_region_widget = QWidget()
        region_layout = QHBoxLayout(self.aws_region_widget)
        region_layout.setContentsMargins(24, 0, 0, 0)
        region_layout.setSpacing(12)
        region_label = QLabel("AWS region")
        region_label.setMinimumWidth(156)
        region_layout.addWidget(region_label)
        self.aws_region_edit = QLineEdit()
        self.aws_region_edit.setMaxLength(_MAX_AWS_REGION_LENGTH)
        self.aws_region_edit.setText("us-east-1")
        self.aws_region_edit.setToolTip("AWS region for Rekognition (1\u201364 characters).")
        self.aws_region_edit.textChanged.connect(self._on_aws_region_changed)
        region_layout.addWidget(self.aws_region_edit)
        region_layout.addStretch(1)
        self.aws_region_widget.setVisible(False)
        layout.addWidget(self.aws_region_widget)

        # --- Detection interval spinbox (Req 13.1) ----------------------
        interval_row = QHBoxLayout()
        interval_row.setSpacing(12)
        interval_label = QLabel("Detection interval")
        interval_label.setMinimumWidth(180)
        interval_row.addWidget(interval_label)
        self.detect_interval_spin = QSpinBox()
        self.detect_interval_spin.setRange(_DETECT_INTERVAL_MIN, _DETECT_INTERVAL_MAX)
        self.detect_interval_spin.setSingleStep(1)
        self.detect_interval_spin.setValue(1)
        self.detect_interval_spin.setToolTip("Run detection every N frames (1\u201360).")
        self.detect_interval_spin.valueChanged.connect(self._on_detect_interval_changed)
        interval_row.addWidget(self.detect_interval_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)

        # Recommendation shown only for the Rekognition backend (Req 13.3).
        self.rekognition_hint = QLabel(_REKOGNITION_INTERVAL_HINT)
        self.rekognition_hint.setWordWrap(True)
        self.rekognition_hint.setStyleSheet(f"color: {_GRAY};")
        self.rekognition_hint.setVisible(False)
        layout.addWidget(self.rekognition_hint)

        # --- Active lanes (manual station override) ---------------------
        # The single-camera pipeline cannot detect lane count, so the number
        # of active inspection lanes is an operator-set value that feeds the
        # deterministic public wait-time formula (product overview §12/§14)
        # rather than a fabricated constant.
        lanes_row = QHBoxLayout()
        lanes_row.setSpacing(12)
        lanes_label = QLabel("Active lanes")
        lanes_label.setMinimumWidth(180)
        lanes_row.addWidget(lanes_label)
        self.active_lanes_spin = QSpinBox()
        self.active_lanes_spin.setRange(_ACTIVE_LANES_MIN, _ACTIVE_LANES_MAX)
        self.active_lanes_spin.setSingleStep(1)
        self.active_lanes_spin.setValue(1)
        self.active_lanes_spin.setToolTip(
            "Number of inspection lanes serving the queue (1\u201399). Set this "
            "to your station's lane count; it feeds the wait-time estimate."
        )
        self.active_lanes_spin.valueChanged.connect(self._on_active_lanes_changed)
        lanes_row.addWidget(self.active_lanes_spin)
        lanes_row.addStretch(1)
        layout.addLayout(lanes_row)

        # Privacy note shown for Rekognition + plate reading (Req 12.9).
        self.privacy_note = QLabel(_PRIVACY_NOTE)
        self.privacy_note.setWordWrap(True)
        self.privacy_note.setStyleSheet(f"color: {_TEAL_DARK}; font-weight: 600;")
        self.privacy_note.setVisible(False)
        layout.addWidget(self.privacy_note)

        # --- No-output mode toggle (Req 15.1) ---------------------------
        self.no_output_toggle = QCheckBox("Disable output video (results table only)")
        self.no_output_toggle.setToolTip(
            "When enabled, no annotated output video is written, so processing "
            "runs faster."
        )
        self.no_output_toggle.toggled.connect(self.on_no_output_toggled)
        layout.addWidget(self.no_output_toggle)

        # --- Output path -------------------------------------------------
        out_row = QHBoxLayout()
        out_row.setSpacing(12)
        out_label = QLabel("Output file")
        out_label.setMinimumWidth(180)
        out_row.addWidget(out_label)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Select a video to set a default output path")
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        out_row.addWidget(self.output_path_edit, 1)

        self.output_browse_button = QPushButton("Browse")
        self.output_browse_button.clicked.connect(self._select_output_path)
        out_row.addWidget(self.output_browse_button)
        layout.addLayout(out_row)

        return card

    # ------------------------------------------------------------------
    # Settings load
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        """Apply persisted settings to the controls before display."""
        self._loading = True
        try:
            s = self._settings.get()

            conf = clamp_confidence(s.confidence)
            self.confidence_slider.setValue(_conf_to_slider(conf))
            self.confidence_value.setValue(conf)

            self.ocr_toggle.setChecked(bool(s.ocr_enabled))
            self.ocr_settings.setVisible(bool(s.ocr_enabled))

            if s.ocr_language:
                if self.ocr_language.findText(s.ocr_language) < 0:
                    self.ocr_language.addItem(s.ocr_language)
                self.ocr_language.setCurrentText(s.ocr_language)

            self.ocr_interval.setValue(max(1, min(100, int(s.ocr_interval))))

            # --- Extension fields (Req 11/12/13/15) ---------------------
            self.source_mode_combo.setCurrentText(
                _SOURCE_MODE_STREAM if s.source_mode == "stream" else _SOURCE_MODE_FILE
            )
            self.detector_combo.setCurrentText(
                _BACKEND_REKOGNITION
                if s.detector_backend == "rekognition"
                else _BACKEND_YOLO
            )
            if isinstance(s.aws_region, str) and s.aws_region.strip():
                self.aws_region_edit.setText(s.aws_region)
            self.detect_interval_spin.setValue(
                max(_DETECT_INTERVAL_MIN, min(_DETECT_INTERVAL_MAX, int(s.detect_interval)))
            )
            self.no_output_toggle.setChecked(bool(s.no_output))
            self.active_lanes_spin.setValue(
                max(_ACTIVE_LANES_MIN, min(_ACTIVE_LANES_MAX, int(s.active_lanes)))
            )
            # Sync conditional visibility/enabled state to restored values.
            # (setCurrentText only emits when the value changes, so apply
            # the handlers explicitly while still in the loading guard.)
            self.on_source_mode_changed(self.source_mode_combo.currentText())
            self.on_detector_backend_changed(self.detector_combo.currentText())
            self.on_no_output_toggled(self.no_output_toggle.isChecked())
        finally:
            self._loading = False

    # ------------------------------------------------------------------
    # File selection / validation
    # ------------------------------------------------------------------

    def select_video_file(self) -> None:
        """Open a native file dialog filtered to MP4, AVI, MOV, MKV."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select input video", "", _VIDEO_FILTER
        )
        if path:
            self._apply_video(path)

    def set_video_from_drop(self, path: str) -> None:
        """Accept a dropped file path — validates and updates the UI."""
        self._apply_video(path)

    def validate_video(self, path: str) -> VideoMetadata | None:
        """Open with cv2.VideoCapture, read one frame, extract metadata.

        Returns a :class:`VideoMetadata` on success, or ``None`` if the file
        cannot be opened or no frame can be read. ``cv2`` is imported lazily
        to avoid pulling heavy pipeline dependencies at module import time.
        """
        try:
            import cv2
        except Exception:  # pragma: no cover - cv2 always present in app env
            return None

        cap = cv2.VideoCapture(path)
        try:
            if not cap.isOpened():
                return None
            ok, _frame = cap.read()
            if not ok or _frame is None:
                return None

            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps is None or fps <= 0:
                fps = 0.0
            duration = frame_count / fps if fps > 0 else 0.0

            return VideoMetadata(
                file_name=os.path.basename(path),
                file_path=path,
                width=width,
                height=height,
                frame_count=frame_count,
                fps=fps,
                duration_seconds=duration,
            )
        finally:
            cap.release()

    def _apply_video(self, path: str) -> None:
        """Validate *path* and update metadata card / error state accordingly."""
        metadata = self.validate_video(path)

        if metadata is None:
            self._metadata = None
            self.summary_card.setVisible(False)
            self._update_start_enabled()
            self._show_error(
                "This file could not be opened. The format may be unsupported "
                "or the file may be corrupt. Choose a different file."
            )
            return

        self._clear_error()
        self._metadata = metadata
        self._populate_summary(metadata)
        self.summary_card.setVisible(True)
        self._update_start_enabled()

        # Default the output path to the input directory unless the user has
        # explicitly chosen a custom path.
        if not self._output_overridden:
            default_out = derive_default_output_path(path)
            self.output_path_edit.setText(default_out)
            self._save_settings(output_path=default_out)

    def _populate_summary(self, metadata: VideoMetadata) -> None:
        minutes, seconds = divmod(int(metadata.duration_seconds), 60)
        self._meta_values["file_name"].setText(metadata.file_name)
        self._meta_values["file_path"].setText(metadata.file_path)
        self._meta_values["resolution"].setText(
            f"{metadata.width} \u00d7 {metadata.height}"
        )
        self._meta_values["frame_count"].setText(f"{metadata.frame_count:,}")
        self._meta_values["duration"].setText(
            f"{minutes}:{seconds:02d} ({metadata.duration_seconds:.1f} s)"
        )
        self._meta_values["fps"].setText(f"{metadata.fps:.2f}")

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    # ------------------------------------------------------------------
    # Parameter control handlers
    # ------------------------------------------------------------------

    def _on_slider_changed(self, position: int) -> None:
        value = _slider_to_conf(position)
        if abs(self.confidence_value.value() - value) > 1e-9:
            self.confidence_value.blockSignals(True)
            self.confidence_value.setValue(value)
            self.confidence_value.blockSignals(False)
        self._save_settings(confidence=value)

    def _on_confidence_spin_changed(self, value: float) -> None:
        slider_pos = _conf_to_slider(value)
        if self.confidence_slider.value() != slider_pos:
            self.confidence_slider.blockSignals(True)
            self.confidence_slider.setValue(slider_pos)
            self.confidence_slider.blockSignals(False)
        self._save_settings(confidence=round(value, 2))

    def _on_confidence_entry_finished(self) -> None:
        """Clamp manually entered confidence to the valid range (Req 8.5)."""
        clamped = clamp_confidence(self.confidence_value.value())
        if abs(clamped - self.confidence_value.value()) > 1e-9:
            self.confidence_value.setValue(clamped)

    def _on_ocr_toggled(self, enabled: bool) -> None:
        self.ocr_settings.setVisible(enabled)
        self._update_privacy_note()
        self._save_settings(ocr_enabled=enabled)

    def _on_ocr_language_changed(self, language: str) -> None:
        self._save_settings(ocr_language=language)

    def _on_ocr_interval_changed(self, interval: int) -> None:
        self._save_settings(ocr_interval=interval)

    # ------------------------------------------------------------------
    # Source mode / backend / interval / no-output handlers (Req 11–15)
    # ------------------------------------------------------------------

    def _source_mode(self) -> str:
        """Return the internal source mode value: 'file' or 'stream'."""
        return (
            "stream"
            if self.source_mode_combo.currentText() == _SOURCE_MODE_STREAM
            else "file"
        )

    def _detector_backend(self) -> str:
        """Return the internal backend value: 'yolo' or 'rekognition'."""
        return (
            "rekognition"
            if self.detector_combo.currentText() == _BACKEND_REKOGNITION
            else "yolo"
        )

    def _update_start_enabled(self) -> None:
        """Enable Start in stream mode, or in file mode once a video loads."""
        if self._source_mode() == "stream":
            self.start_button.setEnabled(True)
        else:
            self.start_button.setEnabled(self._metadata is not None)

    def _update_privacy_note(self) -> None:
        """Show the privacy note only for Rekognition + plate reading (Req 12.9)."""
        show = self._detector_backend() == "rekognition" and self.ocr_toggle.isChecked()
        self.privacy_note.setVisible(show)

    def on_source_mode_changed(self, mode: str) -> None:
        """Toggle file vs stream controls (Req 11.2/11.3)."""
        is_stream = mode == _SOURCE_MODE_STREAM
        # Hide and disable the file selection control in stream mode so file
        # and stream input can never both be active for one session.
        self.select_button.setVisible(not is_stream)
        self.select_button.setEnabled(not is_stream)
        self.stream_url_widget.setVisible(is_stream)
        # The metadata summary only applies to file input.
        self.summary_card.setVisible(not is_stream and self._metadata is not None)
        self._clear_error()
        self._update_start_enabled()
        self._save_settings(source_mode=self._source_mode())

    def _on_stream_url_changed(self, _text: str) -> None:
        # Clear any prior inline error as the user edits the URL.
        if not self._loading:
            self._clear_error()

    def on_detector_backend_changed(self, backend: str) -> None:
        """Toggle AWS region field and Rekognition hints (Req 12.2/12.3/13.3)."""
        is_rekognition = backend == _BACKEND_REKOGNITION
        self.aws_region_widget.setVisible(is_rekognition)
        self.rekognition_hint.setVisible(is_rekognition)
        self._update_privacy_note()
        self._save_settings(detector_backend=self._detector_backend())

    def _on_aws_region_changed(self, _text: str) -> None:
        if not self._loading:
            self._clear_error()
            self._save_settings(aws_region=self.aws_region_edit.text())

    def _on_detect_interval_changed(self, value: int) -> None:
        self._save_settings(detect_interval=int(value))

    def _on_active_lanes_changed(self, value: int) -> None:
        self._save_settings(active_lanes=int(value))

    def on_no_output_toggled(self, enabled: bool) -> None:
        """Disable the output path selector when no-output is enabled (Req 15.2/15.3/15.6)."""
        self.output_path_edit.setEnabled(not enabled)
        self.output_browse_button.setEnabled(not enabled)
        self._save_settings(no_output=enabled)

    def _select_output_path(self) -> None:
        start_dir = self.output_path_edit.text() or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Select output file", start_dir, "MP4 video (*.mp4)"
        )
        if path:
            self._output_overridden = True
            self.output_path_edit.setText(path)
            self._save_settings(output_path=path)

    def _save_settings(self, **kwargs: object) -> None:
        """Persist changed settings (debounced within 2s by SettingsManager)."""
        if self._loading:
            return
        self._settings.update(**kwargs)

    # ------------------------------------------------------------------
    # Config assembly / start
    # ------------------------------------------------------------------

    def build_config(self) -> ProcessingConfig:
        """Collect all parameters into a :class:`ProcessingConfig`."""
        source_mode = self._source_mode()
        detector_backend = self._detector_backend()

        if source_mode == "stream":
            video_path = ""
            stream_url = self.stream_url_edit.text().strip()
        else:
            video_path = self._metadata.file_path if self._metadata else ""
            stream_url = ""

        no_output = self.no_output_toggle.isChecked()
        if no_output:
            output_path: str | None = None
        else:
            output_path = self.output_path_edit.text()
            if not output_path and video_path:
                output_path = derive_default_output_path(video_path)

        aws_region = self.aws_region_edit.text().strip() or "us-east-1"

        return ProcessingConfig(
            video_path=video_path,
            output_path=output_path,
            confidence=clamp_confidence(self.confidence_value.value()),
            ocr_enabled=self.ocr_toggle.isChecked(),
            ocr_languages=[self.ocr_language.currentText() or "en"],
            ocr_interval=self.ocr_interval.value(),
            plate_model_path=None,
            source_mode=source_mode,
            stream_url=stream_url,
            detector_backend=detector_backend,
            aws_region=aws_region,
            detect_interval=self.detect_interval_spin.value(),
            no_output=no_output,
            active_lanes=self.active_lanes_spin.value(),
        )

    def validate_before_start(self) -> str | None:
        """Validate input selections before starting (Req 11.5/11.12/12.5).

        Returns an inline error message when invalid (without mutating field
        state), or ``None`` when the current configuration may start.
        """
        if self._source_mode() == "stream":
            url = self.stream_url_edit.text()
            if not url.strip():
                return "Enter a stream URL to start processing."
            if not is_valid_stream_url(url):
                return (
                    "Enter a stream URL beginning with rtsp://, rtmp://, "
                    "http:// or https://."
                )

        if self._detector_backend() == "rekognition":
            if not is_valid_aws_region(self.aws_region_edit.text()):
                return "Enter an AWS region to use AWS Rekognition."

        return None

    def _on_start_clicked(self) -> None:
        error = self.validate_before_start()
        if error is not None:
            self._show_error(error)
            return
        # In file mode a validated video is required before starting.
        if self._source_mode() == "file" and self._metadata is None:
            return
        self._clear_error()
        self.start_requested.emit(self.build_config())
