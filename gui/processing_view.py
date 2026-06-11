"""ProcessingView: live processing display with annotated frame preview.

Consumes signals emitted by :class:`gui.worker.WorkerThread` only and renders
the latest annotated frame, a progress bar, a statistics panel, and a skipped
frame counter. Emits :attr:`ProcessingView.cancel_requested` when the operator
clicks "Cancel".

Slot signatures mirror the WorkerThread signals exactly:
    - frame_ready(QImage, int, int)  -> on_frame_ready
    - progress(int, int, float, int, float) -> on_progress
    - frame_error(int) -> on_frame_error
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme import BrandTheme
from gui.utils import compute_progress


def format_duration(seconds: float) -> str:
    """Format *seconds* as ``mm:ss`` or ``H:MM:SS`` when an hour or longer.

    Negative or non-finite inputs are treated as zero.
    """
    try:
        total = int(max(0.0, float(seconds)))
    except (TypeError, ValueError):
        total = 0

    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ProcessingView(QWidget):
    """Live processing display with annotated frame preview and progress."""

    # Signals
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._error_count = 0
        self._build_ui()
        self._reset_stats()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(24)

        # Section title (sentence case per brand guidelines)
        title = QLabel("Processing station footage")
        title.setProperty("role", "section-title")
        root.addWidget(title)

        subtitle = QLabel("Detecting vehicles and assigning anonymous IDs.")
        subtitle.setProperty("role", "body")
        subtitle.setProperty("secondary", True)
        root.addWidget(subtitle)

        # Live frame preview card
        preview_card = QFrame()
        preview_card.setProperty("card", True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 12)

        self.frame_label = QLabel("Waiting for first frame…")
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_label.setMinimumSize(640, 360)
        self.frame_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.frame_label.setStyleSheet(
            f"background-color: {BrandTheme.CHARCOAL}; "
            f"color: {BrandTheme.WHITE}; border-radius: 10px;"
        )
        preview_layout.addWidget(self.frame_label)
        root.addWidget(preview_card, stretch=1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        root.addWidget(self.progress_bar)

        # Statistics panel
        stats_card = QFrame()
        stats_card.setProperty("card", True)
        stats_grid = QGridLayout(stats_card)
        stats_grid.setContentsMargins(20, 16, 20, 16)
        stats_grid.setHorizontalSpacing(32)
        stats_grid.setVerticalSpacing(8)

        self.current_frame_value = self._add_stat(stats_grid, 0, 0, "Current frame")
        self.total_frames_value = self._add_stat(stats_grid, 0, 1, "Total frames")
        self.active_count_value = self._add_stat(stats_grid, 0, 2, "Active vehicles")
        self.elapsed_value = self._add_stat(stats_grid, 1, 0, "Elapsed time")
        self.eta_value = self._add_stat(stats_grid, 1, 1, "Estimated remaining")
        self.error_value = self._add_stat(stats_grid, 1, 2, "Skipped frames")

        root.addWidget(stats_card)

        # Cancel button row (right-aligned)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        button_row.addWidget(self.cancel_button)
        root.addLayout(button_row)

    def _add_stat(
        self, grid: QGridLayout, row: int, col: int, label_text: str
    ) -> QLabel:
        """Create a label/value pair in *grid* and return the value label."""
        container = QVBoxLayout()
        container.setSpacing(2)

        caption = QLabel(label_text)
        caption.setProperty("role", "caption")
        container.addWidget(caption)

        value = QLabel("—")
        value.setProperty("role", "card-title")
        container.addWidget(value)

        wrapper = QWidget()
        wrapper.setLayout(container)
        grid.addWidget(wrapper, row, col)
        return value

    def _reset_stats(self) -> None:
        """Reset all statistics and the preview to their initial state."""
        self._error_count = 0
        self.progress_bar.setValue(0)
        self.current_frame_value.setText("0")
        self.total_frames_value.setText("0")
        self.active_count_value.setText("0")
        self.elapsed_value.setText("00:00")
        self.eta_value.setText("--:--")
        self.error_value.setText("0")
        self.frame_label.setText("Waiting for first frame…")
        self.frame_label.setPixmap(QPixmap())

    def reset(self) -> None:
        """Public reset hook used when (re)starting a processing session."""
        self._reset_stats()

    # --------------------------------------------------------------- slots
    @Slot(QImage, int, int)
    def on_frame_ready(self, image: QImage, frame_idx: int, track_count: int) -> None:
        """Update the frame display with the latest annotated image.

        Converts the incoming QImage to a QPixmap scaled to fit the label
        while preserving aspect ratio. Kept lightweight to sustain >= 5 FPS.
        """
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.frame_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.frame_label.setPixmap(scaled)

    @Slot(int, int, float, int, float)
    def on_progress(
        self,
        current: int,
        total: int,
        elapsed: float,
        active_count: int,
        eta: float,
    ) -> None:
        """Update progress bar and statistics labels."""
        self.progress_bar.setValue(int(round(compute_progress(current, total))))
        self.current_frame_value.setText(str(current))
        self.total_frames_value.setText(str(total))
        self.active_count_value.setText(str(active_count))
        self.elapsed_value.setText(format_duration(elapsed))
        self.eta_value.setText(format_duration(eta))

    @Slot(int)
    def on_frame_error(self, error_count: int) -> None:
        """Increment and display skipped frame counter."""
        self._error_count = error_count
        self.error_value.setText(str(error_count))
