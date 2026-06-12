"""MainWindow: application shell, sidebar navigation, and view orchestration.

Hosts the branded header, a sidebar navigation list (with room for future
views), a :class:`QStackedWidget` of the three current views (input,
processing, results), and a persistent privacy trust note footer.

The window owns the :class:`gui.worker.WorkerThread` lifecycle: it validates
preconditions, wires worker signals to view slots (Qt signals/slots only —
Requirement 10.4), and handles completion, errors, and cancellation. It also
implements drag-and-drop video input, close-during-processing confirmation,
window-title state, custom icon, and window-geometry persistence.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.assets import DEFAULT_VEHICLE_MODEL, ensure_model, models_dir, resolve_model
from gui.input_panel import InputPanel
from gui.models import ProcessingConfig
from gui.processing_view import ProcessingView
from gui.resources import ICON_PATH, LOGO_PATH
from gui.results_view import ResultsView
from gui.settings import SettingsManager
from gui.station_controller import StationController
from gui.station_settings_view import StationSettingsView
from gui.station_validation import header_label
from gui.theme import BrandTheme
from gui.utils import is_valid_video_extension
from gui.worker import WorkerThread

# Vehicle detection model. Located via gui.assets.resolve_model, which searches
# assets/models/ and other known locations regardless of working directory
# (Requirement 8.1).
_MODEL_FILENAME = DEFAULT_VEHICLE_MODEL

# Minimum window size (Requirement 1.3).
_MIN_WIDTH = 1024
_MIN_HEIGHT = 700

# Maximum number of captured log lines retained in the panel (Requirement 6.4).
_MAX_LOG_LINES = 10000

# Substrings that mark an AWS Rekognition failure as a credentials problem
# (missing/invalid credentials) versus a region/service/network problem. The
# worker emits errors as ``f"{type(exc).__name__}: {exc}"`` so the boto3
# exception type name appears in the message string (Requirements 12.6, 12.7).
_AWS_CREDENTIAL_MARKERS = (
    "nocredentialserror",
    "partialcredentials",
    "unrecognizedclient",
    "invalidsignature",
    "invalidaccesskey",
    "credential",
)
_AWS_SERVICE_MARKERS = (
    "clienterror",
    "endpointconnectionerror",
    "endpointconnection",
    "botocoreerror",
    "invalidregion",
    "throttl",
)

# Privacy trust note shown in the footer across all views (Requirement 1.5).
_PRIVACY_NOTE = (
    "LaneSight uses temporary anonymous vehicle session IDs for wait-time "
    "calculation. License plates and driver identities are not read or stored "
    "in this prototype."
)

# Navigation entries. The first three map to live views; the remaining three
# are disabled placeholders reserved for future views (Requirement 10.1 — the
# nav must hold at least 6 entries without overflow).
_NAV_INPUT = 0
_NAV_PROCESSING = 1
_NAV_RESULTS = 2
_NAV_STATION = 3

_NAV_ENTRIES = [
    ("input", "Input", True),
    ("processing", "Processing", True),
    ("results", "Results", True),
    ("station", "Station", True),
    # Future views (dashboard, stream config, zone editor) will be added here
    # once implemented. Hidden until then to avoid showing non-functional items.
]

_VIEW_TO_ROW = {
    "input": _NAV_INPUT,
    "processing": _NAV_PROCESSING,
    "results": _NAV_RESULTS,
    "station": _NAV_STATION,
}


class MainWindow(QMainWindow):
    """Top-level application window with sidebar navigation and stacked views."""

    def __init__(self, settings: SettingsManager | None = None) -> None:
        super().__init__()

        self._settings = settings or SettingsManager()
        self._worker: WorkerThread | None = None
        self._cancelling = False
        self._ready = False  # Suppresses geometry saves during construction.

        # Best-effort session metadata captured at processing start, used to
        # populate the results view on completion.
        self._session_fps: float = 0.0
        self._session_ocr_enabled = False
        self._session_output_path: str | None = ""
        self._session_video_name = ""
        self._session_detector_backend = "yolo"
        self._total_frames = 0
        self._skipped_frames = 0
        # Operator-configured active lanes captured at session start; feeds the
        # deterministic wait-time estimate on the Results view.
        self._session_active_lanes = 1

        self._apply_theme()
        self._build_ui()
        self._set_window_icon()

        self.setAcceptDrops(True)
        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        self._restore_geometry()

        self.switch_view("input")
        self._ready = True

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        """Apply the Opus brand theme/stylesheet (Requirements 1.2, 7.x)."""
        app = QApplication.instance()
        if isinstance(app, QApplication):
            BrandTheme.apply(app)
        else:  # pragma: no cover - app always exists in normal runs
            self.setStyleSheet(BrandTheme.get_stylesheet())

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Middle band: sidebar nav + stacked views.
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.input_panel = InputPanel(self._settings)
        self.processing_view = ProcessingView()
        self.results_view = ResultsView()
        # Station controller: single source of truth for the active
        # StationConfig. Constructed after _build_header() (above) created
        # self._station_label, so the initial label update at the end of this
        # method can render the active value. The controller emits any
        # load-time warnings/station_changed during its own construction
        # (before these slots are connected), so the header is seeded
        # explicitly via _update_station_label() below (Req 4.1).
        self.station_controller = StationController(self._settings)
        self.station_controller.station_changed.connect(self._update_station_label)
        self.station_controller.warning.connect(self._show_station_warning)
        self.station_settings_view = StationSettingsView(self.station_controller)
        # Wrap each view in a scroll area so content scrolls rather than being
        # compressed (which overlaps widgets) when the window is short — e.g.
        # at high display-scaling factors. Views keep their natural height.
        self.stack.addWidget(self._scrollable(self.input_panel))      # index 0
        self.stack.addWidget(self._scrollable(self.processing_view))  # index 1
        self.stack.addWidget(self._scrollable(self.results_view))     # index 2
        self.stack.addWidget(self._scrollable(self.station_settings_view))  # index 3
        middle.addWidget(self.stack, stretch=1)

        root.addLayout(middle, stretch=1)
        root.addWidget(self._build_log_panel())
        root.addWidget(self._build_footer())

        self.setCentralWidget(central)

        # Wire view signals (Qt signals/slots only — Requirement 10.4).
        self.input_panel.start_requested.connect(self.start_processing)
        self.processing_view.cancel_requested.connect(self._on_cancel_requested)
        self.results_view.new_session_requested.connect(
            lambda: self.switch_view("input")
        )

        # Seed the header with the active station now that the label and the
        # controller both exist (Req 4.1). The signal payload is the effective
        # display name; read it from the controller's active config.
        self._update_station_label(
            self.station_controller.active().effective_display_name
        )

    def _scrollable(self, widget: QWidget) -> QScrollArea:
        """Wrap *widget* in a vertical scroll area that resizes to the viewport.

        Keeps the view at its natural height; when the window is too short the
        content scrolls instead of being compressed below its minimum size
        (which would otherwise overlap widgets at high display-scaling).
        """
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        area.setWidget(widget)
        return area

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setProperty("header", True)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(32, 18, 32, 18)
        layout.setSpacing(20)

        # Opus logo (>= 36px height, unmodified) with text fallback.
        logo_label = QLabel()
        pixmap = QPixmap(str(LOGO_PATH)) if LOGO_PATH.exists() else QPixmap()
        if not pixmap.isNull():
            scaled = pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled)
        else:  # pragma: no cover - logo asset is present in resources
            logo_label.setText("OPUS")
            logo_label.setStyleSheet(
                f"color: {BrandTheme.WHITE}; font-size: 28px; font-weight: 700;"
            )
        layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title = QLabel("Opus LaneSight")
        title.setStyleSheet(
            f"color: {BrandTheme.WHITE}; font-size: 30px; font-weight: 700;"
        )
        subtitle = QLabel("AI-powered station wait-time intelligence")
        subtitle.setStyleSheet(
            f"color: {BrandTheme.WHITE}; font-size: 14px; font-weight: 400;"
        )
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        layout.addLayout(text_box)
        layout.addStretch(1)

        # Right-aligned active station label (Req 4.1). White text on the
        # gradient header, matching the title styling.
        self._station_label = QLabel("")
        self._station_label.setStyleSheet(
            f"color: {BrandTheme.WHITE}; font-size: 16px; font-weight: 600;"
        )
        self._station_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._station_label, 0, Qt.AlignmentFlag.AlignVCenter)

        return header

    def _build_sidebar(self) -> QListWidget:
        self.nav = QListWidget()
        self.nav.setObjectName("sidebarNav")
        self.nav.setFixedWidth(200)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setStyleSheet(
            f"""
            QListWidget#sidebarNav {{
                background-color: {BrandTheme.WHITE};
                border-right: 1px solid {BrandTheme.CARD_BORDER};
                padding: 12px 8px;
                font-size: 15px;
            }}
            QListWidget#sidebarNav::item {{
                padding: 12px 14px;
                border-radius: 10px;
                margin: 2px 0;
                color: {BrandTheme.CHARCOAL};
            }}
            QListWidget#sidebarNav::item:selected {{
                background-color: {BrandTheme.TEAL};
                color: {BrandTheme.WHITE};
            }}
            QListWidget#sidebarNav::item:disabled {{
                color: {BrandTheme.GRAY};
            }}
            """
        )

        for _name, label, enabled in _NAV_ENTRIES:
            item = QListWidgetItem(label)
            if not enabled:
                # Disabled placeholders: non-selectable, reserved for future views.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("Coming soon")
            self.nav.addItem(item)

        self.nav.currentRowChanged.connect(self._on_nav_row_changed)
        return self.nav

    def _build_log_panel(self) -> QFrame:
        """Build the collapsible pipeline log panel (Requirement 6.4).

        A toggle button shows/hides a read-only :class:`QPlainTextEdit` that
        receives captured pipeline stdout/stderr. The panel is collapsed by
        default. ``setMaximumBlockCount`` caps the retained lines at 10,000 so
        long runs cannot grow the buffer without bound.
        """
        container = QFrame()
        container.setStyleSheet(
            f"background-color: {BrandTheme.WHITE}; "
            f"border-top: 1px solid {BrandTheme.CARD_BORDER};"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 8, 32, 8)
        layout.setSpacing(8)

        # Toggle control (sentence-case label — Requirement 7.5).
        self.log_toggle = QPushButton("Show log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.setStyleSheet(
            f"""
            QPushButton {{
                color: {BrandTheme.TEAL};
                background-color: transparent;
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {BrandTheme.BG};
            }}
            QPushButton:checked {{
                color: {BrandTheme.WHITE};
                background-color: {BrandTheme.TEAL};
                border-color: {BrandTheme.TEAL};
            }}
            """
        )
        self.log_toggle.toggled.connect(self._on_log_toggled)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        # Read-only log view. setMaximumBlockCount bounds the visible lines to
        # the most recent 10,000 efficiently (Requirement 6.4).
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(_MAX_LOG_LINES)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setFixedHeight(180)
        self.log_view.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {BrandTheme.BG};
                color: {BrandTheme.CHARCOAL};
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 10px;
                padding: 8px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }}
            """
        )
        self.log_view.setVisible(False)  # Collapsed by default.
        layout.addWidget(self.log_view)

        return container

    def _on_log_toggled(self, checked: bool) -> None:
        """Show or hide the log view and update the toggle label."""
        self.log_view.setVisible(checked)
        self.log_toggle.setText("Hide log" if checked else "Show log")

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setStyleSheet(
            f"background-color: {BrandTheme.WHITE}; "
            f"border-top: 1px solid {BrandTheme.CARD_BORDER};"
        )
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(32, 10, 32, 10)

        note = QLabel(_PRIVACY_NOTE)
        note.setWordWrap(True)
        note.setProperty("role", "caption")
        note.setProperty("secondary", True)
        note.setStyleSheet(f"color: {BrandTheme.GRAY}; font-size: 12px;")
        layout.addWidget(note)
        return footer

    def _set_window_icon(self) -> None:
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

    # ------------------------------------------------------------------
    # Navigation / view switching
    # ------------------------------------------------------------------

    def _on_nav_row_changed(self, row: int) -> None:
        """Handle sidebar selection changes for the three live views."""
        for name, target in _VIEW_TO_ROW.items():
            if target == row:
                if self.stack.currentIndex() != row:
                    self.switch_view(name)
                break

    def switch_view(self, view_name: str) -> None:
        """Switch the active view in the stack and update the window title."""
        row = _VIEW_TO_ROW.get(view_name)
        if row is None:
            return

        self.stack.setCurrentIndex(row)

        # Keep the sidebar selection in sync without re-entering the handler.
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(row)
        self.nav.blockSignals(False)

        if view_name == "input":
            self.setWindowTitle("Opus LaneSight - Ready")
        elif view_name == "processing":
            name = self._session_video_name or ""
            self.setWindowTitle(
                f"Opus LaneSight - Processing{(' ' + name) if name else ''}"
            )
        elif view_name == "results":
            self.setWindowTitle("Opus LaneSight - Results")
        elif view_name == "station":
            self.setWindowTitle("Opus LaneSight - Station")

    def _update_station_label(self, display_name: str) -> None:
        """Render the active Station_Display_Name in the header (Req 4.1, 4.4).

        Applies :func:`header_label` truncation at 40 chars and exposes the
        full value as a tooltip on hover/focus (Req 4.2). When no active config
        is loaded (empty display name), shows the "No station selected"
        placeholder (Req 4.5). The header is persistent across views, so the
        active station renders on every view (Req 4.1, 4.4).
        """
        if not display_name:
            self._station_label.setText("No station selected")
            self._station_label.setToolTip("")
            return

        shown, full = header_label(display_name)
        self._station_label.setText(shown)
        self._station_label.setToolTip(full if full is not None else "")

    def _show_station_warning(self, message: str) -> None:
        """Display a non-blocking station warning (Req 3.4, 3.5, 3.6).

        Routes the message to the pipeline log panel so it never blocks
        processing or record production, consistent with the existing
        non-blocking log-routing pattern.
        """
        log_view = getattr(self, "log_view", None)
        if log_view is not None:
            log_view.appendPlainText(f"Station warning: {message}")

    # ------------------------------------------------------------------
    # Processing lifecycle
    # ------------------------------------------------------------------

    def start_processing(self, config: ProcessingConfig) -> None:
        """Validate preconditions, launch the worker, and show processing view."""
        # Requirement 8.1 — the local vehicle detection model must be available.
        # This check applies only to the local YOLOv8 backend; the AWS
        # Rekognition backend needs no local model (Requirement 12.4), so it is
        # skipped when detector_backend == "rekognition".
        if config.detector_backend != "rekognition":
            has_plate_model = (
                config.plate_model_path is not None
                and Path(config.plate_model_path).exists()
            )
            model_available = resolve_model(_MODEL_FILENAME) is not None
            # Attempt a one-time auto-download of the default model when it is
            # missing (Requirement 8.1). Ultralytics fetches the official
            # weights into assets/models/. Use a wait cursor since the download
            # blocks briefly on first run.
            if not model_available and not has_plate_model:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    model_available = ensure_model(_MODEL_FILENAME) is not None
                finally:
                    QApplication.restoreOverrideCursor()
            if not model_available and not has_plate_model:
                QMessageBox.critical(
                    self,
                    "Detection model missing",
                    f"The vehicle detection model '{_MODEL_FILENAME}' was not "
                    f"found and could not be downloaded automatically.\n\n"
                    f"Check your internet connection, or place "
                    f"'{_MODEL_FILENAME}' in '{models_dir()}' (or select a model "
                    f"via settings), then try again.",
                )
                return

        # Requirement 8.2 — output path directory must be writable. Skipped in
        # No_Output_Mode (config.output_path is None — Requirement 15.4) and for
        # streams without recording, where no output file is written.
        if config.output_path is not None and not self._output_path_writable(
            config.output_path
        ):
            QMessageBox.critical(
                self,
                "Output path not writable",
                "The selected output location cannot be written to. The folder "
                "may not exist or you may lack permission.\n\nChoose a different "
                "output file path and try again.",
            )
            return

        # Capture session metadata for the results view (best-effort). In stream
        # mode video_path is "" so the stream URL identifies the session in the
        # window title (Requirements 11.x).
        is_stream = config.source_mode == "stream"
        self._session_ocr_enabled = config.ocr_enabled
        self._session_output_path = config.output_path  # may be None
        self._session_detector_backend = config.detector_backend
        self._session_video_name = (
            config.stream_url if is_stream else os.path.basename(config.video_path)
        )
        self._session_fps = self._lookup_session_fps()
        self._total_frames = 0
        self._skipped_frames = 0
        self._session_active_lanes = config.active_lanes

        # Create and wire the worker (Qt signals/slots only — Requirement 10.4).
        self._worker = WorkerThread(config)
        self._worker.frame_ready.connect(self.processing_view.on_frame_ready)
        self._worker.progress.connect(self.processing_view.on_progress)
        self._worker.progress.connect(self._track_progress)
        self._worker.frame_error.connect(self.processing_view.on_frame_error)
        self._worker.frame_error.connect(self._track_frame_error)
        self._worker.connecting.connect(self.processing_view.on_connecting)
        self._worker.reconnect_status.connect(
            self.processing_view.on_reconnect_status
        )
        self._worker.processing_finished.connect(self.on_worker_finished)
        self._worker.error.connect(self.on_worker_error)
        self._worker.log_output.connect(self._on_log_output)
        self._worker.finished.connect(self._on_thread_finished)

        self.processing_view.reset()
        # Stream mode shows indeterminate progress and a "Stop" label (Req 11.6,
        # 11.10); file mode keeps determinate progress.
        self.processing_view.set_stream_mode(is_stream)
        self.switch_view("processing")
        self._worker.start()

    def on_worker_finished(self, results: list) -> None:
        """Handle pipeline completion — populate and switch to the results view.

        Producing results clears any pending cancellation flag: a stream "Stop"
        emits ``processing_finished`` with the tracks collected so far (Req
        11.10), and the subsequent ``QThread.finished`` handler must not then
        override the Results_View by returning to the input view. A file
        "Cancel" never reaches here (no completion signal is emitted), so it
        still returns to the input view via ``_on_thread_finished``.
        """
        self._cancelling = False
        # Surface the active Station_Display_Name in the results header,
        # captured from the StationController at display time (Req 6.4). The
        # controller is the single source of truth for the active identity and
        # is constructed at launch (Req 3.2), so the value is always available.
        self.results_view.set_station_display_name(
            self.station_controller.active().effective_display_name
        )
        self.results_view.display_results(
            results,
            self._session_fps,
            self._session_ocr_enabled,
            self._session_output_path,
            self._skipped_frames,
            self._total_frames,
            self._session_active_lanes,
        )
        self.switch_view("results")

    def on_worker_error(self, error_msg: str, frame_idx: int) -> None:
        """Handle a pipeline error — show a dialog and return to the input view.

        AWS Rekognition failures are classified into credentials errors
        (Requirement 12.6) versus region/service/network errors
        (Requirement 12.7) by inspecting the worker's error message, which
        carries the boto3 exception type name. Returning to the Video_Input_Panel
        retains the user's selections (the panel persists them via settings).
        """
        title, body = self._classify_error(error_msg, frame_idx)
        QMessageBox.critical(self, title, body)
        self.switch_view("input")

    @staticmethod
    def _classify_error(error_msg: str, frame_idx: int) -> tuple[str, str]:
        """Map a worker error message to a (dialog title, body) pair.

        The worker emits errors as ``f"{type(exc).__name__}: {exc}"``, so boto3
        exception type names appear verbatim. Credentials markers take priority
        over service/region markers; anything else falls back to the generic
        processing-error message.
        """
        lowered = error_msg.lower()

        if any(marker in lowered for marker in _AWS_CREDENTIAL_MARKERS):
            return (
                "AWS credentials error",
                "AWS Rekognition could not authenticate. Missing or invalid AWS "
                "credentials stopped processing.\n\nConfigure valid AWS "
                "credentials (environment variables, shared config, or instance "
                "profile), then try again.\n\n"
                f"Details: {error_msg}",
            )

        if any(marker in lowered for marker in _AWS_SERVICE_MARKERS):
            return (
                "AWS Rekognition error",
                "An AWS Rekognition API call failed due to a region, network, or "
                "service error. Processing stopped.\n\nVerify the AWS region and "
                "your network connection, then try again.\n\n"
                f"Details: {error_msg}",
            )

        return (
            "Processing error",
            f"Processing stopped at frame {frame_idx}.\n\n{error_msg}",
        )

    def _on_cancel_requested(self) -> None:
        """User clicked Cancel in the processing view."""
        if self._worker is not None and self._worker.isRunning():
            self._cancelling = True
            self._worker.request_cancel()

    def _on_thread_finished(self) -> None:
        """QThread completed. If it was cancelled, return to the input view."""
        if self._cancelling:
            self._cancelling = False
            self.switch_view("input")
            QMessageBox.information(
                self,
                "Processing cancelled",
                "Processing was cancelled. Any incomplete output was discarded.",
            )

    # ------------------------------------------------------------------
    # Worker signal tracking helpers
    # ------------------------------------------------------------------

    def _track_progress(
        self, current: int, total: int, elapsed: float, active: int, eta: float
    ) -> None:
        if total > 0:
            self._total_frames = total

    def _track_frame_error(self, count: int) -> None:
        self._skipped_frames = count

    def _on_log_output(self, line: str) -> None:
        """Append a captured pipeline stdout/stderr line to the log panel.

        The :class:`QPlainTextEdit` is capped at 10,000 blocks via
        ``setMaximumBlockCount`` (Requirement 6.4), so appending is O(1) and the
        oldest lines are discarded automatically. Routing output here ensures
        pipeline ``print`` statements never reach a background console window.
        """
        text = line.rstrip("\n")
        self.log_view.appendPlainText(text)

    # ------------------------------------------------------------------
    # Validation / metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _output_path_writable(output_path: str) -> bool:
        if not output_path:
            return False
        directory = os.path.dirname(os.path.abspath(output_path))
        return os.path.isdir(directory) and os.access(directory, os.W_OK)

    def _lookup_session_fps(self) -> float:
        """Best-effort FPS lookup from the input panel's validated metadata."""
        metadata = getattr(self.input_panel, "_metadata", None)
        if metadata is not None and getattr(metadata, "fps", 0):
            return float(metadata.fps)
        return 0.0

    # ------------------------------------------------------------------
    # Drag and drop (Requirements 9.5, 9.6)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags that contain at least one valid-extension video file."""
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and is_valid_video_extension(url.toLocalFile()):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Validate the dropped file and forward it to the input panel."""
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        local_path = next(
            (u.toLocalFile() for u in mime.urls() if u.isLocalFile()), ""
        )
        if not local_path:
            event.ignore()
            return

        if not is_valid_video_extension(local_path):
            event.ignore()
            QMessageBox.warning(
                self,
                "Unsupported file",
                "That file type is not supported. Drop an MP4, AVI, MOV, or MKV "
                "video file.",
            )
            return

        event.acceptProposedAction()
        # Return to the input view and let it validate/open the file. The panel
        # surfaces an inline error if OpenCV cannot read the file (Req 9.6).
        self.switch_view("input")
        self.input_panel.set_video_from_drop(local_path)

    # ------------------------------------------------------------------
    # Window management (Requirements 9.1, 9.2) + geometry persistence (5.1)
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Confirm exit while processing is active."""
        if self._worker is not None and self._worker.isRunning():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Processing in progress")
            box.setText("Processing is still running. What would you like to do?")
            cancel_exit = box.addButton(
                "Cancel and exit", QMessageBox.ButtonRole.AcceptRole
            )
            box.addButton("Continue processing", QMessageBox.ButtonRole.RejectRole)
            box.exec()

            if box.clickedButton() is cancel_exit:
                self._cancelling = False  # Don't switch views while closing.
                self._worker.request_cancel()
                self._worker.wait(3000)
                event.accept()
            else:
                event.ignore()
            return

        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt event type
        super().resizeEvent(event)
        self._persist_geometry()

    def moveEvent(self, event) -> None:  # noqa: ANN001 - Qt event type
        super().moveEvent(event)
        self._persist_geometry()

    def _restore_geometry(self) -> None:
        s = self._settings.get()
        self.resize(s.window_width, s.window_height)
        if s.window_x is not None and s.window_y is not None:
            self.move(s.window_x, s.window_y)

    def _persist_geometry(self) -> None:
        if not self._ready:
            return
        self._settings.update(
            window_width=self.width(),
            window_height=self.height(),
            window_x=self.x(),
            window_y=self.y(),
        )
