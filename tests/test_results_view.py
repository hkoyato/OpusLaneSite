"""Unit tests for :class:`gui.results_view.ResultsView`.

Exercises ``display_results`` for column visibility under OCR on/off, the
empty-state stack switch, header-click sort behavior, and summary statistics
that exclude vehicles without a leave time. Runs headless via the ``qapp``
fixture (offscreen Qt platform).

Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from gui.models import TrackResult
from gui.results_view import ResultsView

# Column indices mirror gui.results_view.
_COL_PLATE_TEXT = 1
_COL_CONFIDENCE = 2
_COL_ENTER_TIME = 3

_DASH = "\u2014"


def make_result(
    vehicle_id: int,
    enter_time: float,
    leave_time: float | None,
    *,
    plate_text: str = "",
    plate_confidence: float = 0.0,
    fps: float = 1.0,
) -> TrackResult:
    """Build a TrackResult with consistent frame/time/wait values."""
    first_frame = int(round(enter_time * fps))
    last_frame = first_frame if leave_time is None else int(round(leave_time * fps))
    wait_time = None if leave_time is None else leave_time - enter_time
    return TrackResult(
        vehicle_id=vehicle_id,
        plate_text=plate_text,
        plate_confidence=plate_confidence,
        first_frame=first_frame,
        last_frame=last_frame,
        enter_time=enter_time,
        leave_time=leave_time,
        wait_time=wait_time,
    )


@pytest.fixture()
def view(qapp):
    """Provide a fresh ResultsView for each test."""
    return ResultsView()


# ---------------------------------------------------------- column structure
def test_table_has_six_columns(view):
    """Table always exposes the six result columns. (Req 4.1)"""
    assert view._table.columnCount() == 6


def test_columns_hidden_when_ocr_disabled(view):
    """Plate text and confidence columns hide when OCR is off. (Req 4.6)"""
    results = [make_result(1, 0.0, 5.0)]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=10)
    assert view._table.isColumnHidden(_COL_PLATE_TEXT) is True
    assert view._table.isColumnHidden(_COL_CONFIDENCE) is True


def test_columns_visible_when_ocr_enabled(view):
    """Plate text and confidence columns show when OCR is on. (Req 4.6)"""
    results = [make_result(1, 0.0, 5.0, plate_text="ABC123", plate_confidence=0.9)]
    view.display_results(results, fps=1.0, ocr_enabled=True, output_path="",
                         skipped_frames=0, total_frames=10)
    assert view._table.isColumnHidden(_COL_PLATE_TEXT) is False
    assert view._table.isColumnHidden(_COL_CONFIDENCE) is False


# ----------------------------------------------------------------- empty state
def test_empty_state_shown_when_no_results(view):
    """The empty-state page (stack index 1) shows with no results. (Req 4.7)"""
    view.display_results([], fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=10)
    assert view._content_stack.currentIndex() == 1


def test_table_shown_when_results_present(view):
    """The table page (stack index 0) shows when results exist. (Req 4.7)"""
    view.display_results([make_result(1, 0.0, 5.0)], fps=1.0, ocr_enabled=False,
                         output_path="", skipped_frames=0, total_frames=10)
    assert view._content_stack.currentIndex() == 0


# ---------------------------------------------------------------- sort order
def _enter_column_values(view) -> list[float]:
    return [
        float(view._table.item(row, _COL_ENTER_TIME).text())
        for row in range(view._table.rowCount())
    ]


def test_default_sort_ascending_by_enter_time(view):
    """Rows default to ascending enter-time order. (Req 4.3)"""
    # Supplied out of order: 7.0, 1.0, 4.0.
    results = [
        make_result(1, 7.0, 9.0),
        make_result(2, 1.0, 3.0),
        make_result(3, 4.0, 6.0),
    ]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=20)
    assert _enter_column_values(view) == [1.0, 4.0, 7.0]


def test_header_click_sort_reverses_order(view):
    """A descending header sort reverses the enter-time order. (Req 4.3)"""
    results = [
        make_result(1, 7.0, 9.0),
        make_result(2, 1.0, 3.0),
        make_result(3, 4.0, 6.0),
    ]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=20)
    assert _enter_column_values(view) == [1.0, 4.0, 7.0]

    # Simulate a header click toggling to descending order.
    view._table.sortItems(_COL_ENTER_TIME, Qt.SortOrder.DescendingOrder)
    assert _enter_column_values(view) == [7.0, 4.0, 1.0]


# ------------------------------------------------------------ summary stats
def test_summary_excludes_vehicles_without_leave_time(view):
    """Avg/max/min use only complete tracks; total counts all. (Req 4.2, 4.8)"""
    results = [
        make_result(1, 0.0, 10.0),   # wait 10.0
        make_result(2, 0.0, 4.0),    # wait 4.0
        make_result(3, 0.0, None),   # still in frame, excluded
    ]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=20)

    labels = view._summary_value_labels
    assert labels["total_vehicles"].text() == "3"
    # Complete tracks have waits 10.0 and 4.0 -> avg 7.0, max 10.0, min 4.0.
    assert labels["avg_wait"].text() == "7.0"
    assert labels["max_wait"].text() == "10.0"
    assert labels["min_wait"].text() == "4.0"


def test_summary_all_dashes_when_no_complete_tracks(view):
    """Wait metrics show an em dash when no track has a leave time. (Req 4.8)"""
    results = [make_result(1, 0.0, None), make_result(2, 1.0, None)]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path="",
                         skipped_frames=0, total_frames=20)

    labels = view._summary_value_labels
    assert labels["total_vehicles"].text() == "2"
    assert labels["avg_wait"].text() == _DASH
    assert labels["max_wait"].text() == _DASH
    assert labels["min_wait"].text() == _DASH
