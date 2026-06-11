"""Results view for the Opus LaneSight GUI.

Displays per-vehicle wait-time results in a sortable table alongside summary
metric cards, a skipped-frame warning, the output file path with an
"Open folder" action, and a "New session" button.

This widget is self-contained and communicates only via the
``new_session_requested`` signal, per the design's view-independence rule.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.models import TrackResult
from gui.theme import BrandTheme
from gui.utils import compute_summary, sort_results_default

# Column indices for the vehicle table.
_COL_VEHICLE_ID = 0
_COL_PLATE_TEXT = 1
_COL_CONFIDENCE = 2
_COL_ENTER_TIME = 3
_COL_LEAVE_TIME = 4
_COL_WAIT_TIME = 5

_HEADERS = [
    "Vehicle ID",
    "Plate text",
    "Confidence",
    "Enter time (s)",
    "Leave time (s)",
    "Wait time (s)",
]

# Placeholder shown for vehicles that never left the frame.
_DASH = "\u2014"  # em dash


class _NumericItem(QTableWidgetItem):
    """Table item that sorts by a stored numeric value, not display text.

    Vehicles with no leave/wait time store ``float('inf')`` so they sort to
    the end in ascending order while still displaying an em dash.
    """

    def __init__(self, display: str, sort_value: float) -> None:
        super().__init__(display)
        self._sort_value = sort_value
        # Keep the cell read-only.
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other: object) -> bool:  # noqa: D401 - Qt sort hook
        if isinstance(other, _NumericItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)  # type: ignore[arg-type]


class ResultsView(QWidget):
    """Post-processing results display with table and summary statistics."""

    new_session_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._output_path: str = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(24)

        # Section title
        title = QLabel("Results")
        title.setProperty("role", "section-title")
        root.addWidget(title)

        # Summary metric cards
        self._summary_value_labels: dict[str, QLabel] = {}
        root.addLayout(self._build_summary_cards())

        # Skipped-frame warning (hidden unless skipped > 0)
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            f"color: {BrandTheme.ORANGE}; font-size: 14px; font-weight: 600;"
        )
        self._warning_label.setVisible(False)
        root.addWidget(self._warning_label)

        # Stacked area: table vs. empty state
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._build_table())  # index 0
        self._content_stack.addWidget(self._build_empty_state())  # index 1
        root.addWidget(self._content_stack, stretch=1)

        # Output path row + Open folder
        root.addLayout(self._build_output_row())

        # New session button
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        new_session_btn = QPushButton("New session")
        new_session_btn.clicked.connect(self.new_session_requested.emit)
        button_row.addWidget(new_session_btn)
        root.addLayout(button_row)

    def _build_summary_cards(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(16)
        cards = [
            ("total_vehicles", "Total vehicles"),
            ("avg_wait", "Average wait (s)"),
            ("max_wait", "Maximum wait (s)"),
            ("min_wait", "Minimum wait (s)"),
        ]
        for col, (key, label_text) in enumerate(cards):
            card = QFrame()
            card.setProperty("card", True)
            card.setStyleSheet(BrandTheme.card_style())
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(8)

            label = QLabel(label_text)
            label.setProperty("role", "card-title")
            label.setProperty("secondary", True)

            value = QLabel(_DASH)
            value.setProperty("role", "metric")

            card_layout.addWidget(label)
            card_layout.addWidget(value)
            self._summary_value_labels[key] = value
            grid.addWidget(card, 0, col)
            grid.setColumnStretch(col, 1)
        return grid

    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        # Built-in header-click sorting toggles ascending/descending.
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        return self._table

    def _build_empty_state(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        message = QLabel(
            "No vehicles currently detected.\n"
            "Start a new session to process another video."
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setProperty("role", "body")
        message.setProperty("secondary", True)
        layout.addWidget(message)
        return container

    def _build_output_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        prefix = QLabel("Output file:")
        prefix.setProperty("secondary", True)
        row.addWidget(prefix)

        self._output_path_label = QLabel(_DASH)
        self._output_path_label.setProperty("role", "body")
        self._output_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._output_path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self._output_path_label, stretch=1)

        self._open_folder_btn = QPushButton("Open folder")
        self._open_folder_btn.clicked.connect(self.open_output_folder)
        self._open_folder_btn.setEnabled(False)
        row.addWidget(self._open_folder_btn)
        return row

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display_results(
        self,
        results: list[TrackResult],
        fps: float,  # noqa: ARG002 - times are precomputed on TrackResult
        ocr_enabled: bool,
        output_path: str,
        skipped_frames: int,
        total_frames: int,
    ) -> None:
        """Populate the table and summary cards from *results*.

        Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 8.4
        """
        self._output_path = output_path

        # Output path + Open folder enablement.
        self._output_path_label.setText(output_path or _DASH)
        self._open_folder_btn.setEnabled(bool(output_path))

        # Skipped-frame warning (orange, only when > 0).
        if skipped_frames > 0:
            self._warning_label.setText(
                f"{skipped_frames} of {total_frames} frames were skipped "
                f"during processing due to read errors."
            )
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setVisible(False)

        # Column visibility based on OCR.
        self._table.setColumnHidden(_COL_PLATE_TEXT, not ocr_enabled)
        self._table.setColumnHidden(_COL_CONFIDENCE, not ocr_enabled)

        # Summary cards.
        self._update_summary(compute_summary(results))

        # Empty state vs. table.
        if not results:
            self._table.setRowCount(0)
            self._content_stack.setCurrentIndex(1)
            return
        self._content_stack.setCurrentIndex(0)

        self._populate_table(sort_results_default(results))

    def open_output_folder(self) -> None:
        """Open the folder containing the output file in Windows Explorer.

        Validates: Requirements 4.4
        """
        if not self._output_path:
            return
        folder = str(Path(self._output_path).parent)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows-only
        except (OSError, AttributeError):
            # Non-fatal: folder may not exist or platform lacks startfile.
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_summary(self, summary: dict) -> None:
        self._summary_value_labels["total_vehicles"].setText(
            str(summary["total_vehicles"])
        )
        for key in ("avg_wait", "max_wait", "min_wait"):
            value = summary[key]
            self._summary_value_labels[key].setText(
                _DASH if value is None else f"{value:.1f}"
            )

    def _populate_table(self, results: list[TrackResult]) -> None:
        # Disable sorting while inserting to avoid row-shuffle during fill.
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))

        for row, r in enumerate(results):
            # Vehicle ID (numeric sort).
            self._table.setItem(
                row, _COL_VEHICLE_ID, _NumericItem(str(r.vehicle_id), float(r.vehicle_id))
            )

            # Plate text (lexicographic).
            plate_item = QTableWidgetItem(r.plate_text or "")
            plate_item.setFlags(plate_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, _COL_PLATE_TEXT, plate_item)

            # Confidence (2 decimals, numeric sort).
            self._table.setItem(
                row,
                _COL_CONFIDENCE,
                _NumericItem(f"{r.plate_confidence:.2f}", r.plate_confidence),
            )

            # Enter time (1 decimal, numeric sort).
            self._table.setItem(
                row,
                _COL_ENTER_TIME,
                _NumericItem(f"{r.enter_time:.1f}", r.enter_time),
            )

            # Leave time (em dash when None, sorts to end).
            if r.leave_time is None:
                leave_item = _NumericItem(_DASH, float("inf"))
            else:
                leave_item = _NumericItem(f"{r.leave_time:.1f}", r.leave_time)
            self._table.setItem(row, _COL_LEAVE_TIME, leave_item)

            # Wait time (em dash when None, sorts to end).
            if r.wait_time is None:
                wait_item = _NumericItem(_DASH, float("inf"))
            else:
                wait_item = _NumericItem(f"{r.wait_time:.1f}", r.wait_time)
            self._table.setItem(row, _COL_WAIT_TIME, wait_item)

        self._table.setSortingEnabled(True)
        # Default sort: ascending by enter time.
        self._table.sortItems(_COL_ENTER_TIME, Qt.SortOrder.AscendingOrder)
