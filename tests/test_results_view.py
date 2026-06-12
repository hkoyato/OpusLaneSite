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


# ============================================================================
# ResultsView extensions: deduplicated display, summary-from-rows, No_Output_Mode
#
# Validates: Requirements 14.1, 14.4, 14.5, 15.5
#
# The view renders the rows it receives as-is: when Plate_Text_Reading is
# enabled the worker has already applied Plate_Deduplication (one row per
# physical plate) and the Plate Text / Confidence columns are shown; when
# disabled every track is a separate row and those columns are hidden. Summary
# statistics are computed from the displayed row set. When output_path is None
# (No_Output_Mode) the path display and open-folder control are hidden and a
# "No output video written" message is shown instead.
# ============================================================================


def _vehicle_id_column_values(view) -> list[int]:
    """Return the Vehicle ID column values across all displayed rows."""
    from gui.results_view import _COL_VEHICLE_ID

    return [
        int(view._table.item(row, _COL_VEHICLE_ID).text())
        for row in range(view._table.rowCount())
    ]


# --------------------------------------- deduplicated vs separate rows (14.1/14.4)
def test_deduplicated_rows_shown_with_plate_columns_when_ocr_enabled(view):
    """With OCR on, the view displays the (deduplicated) rows it is given and
    shows the plate columns. (Req 14.1)"""
    # Two physical plates: the worker already merged duplicates into 2 rows.
    deduped = [
        make_result(1, 0.0, 5.0, plate_text="ABC123", plate_confidence=0.91),
        make_result(2, 1.0, 7.0, plate_text="XYZ789", plate_confidence=0.88),
    ]
    view.display_results(deduped, fps=1.0, ocr_enabled=True, output_path="out.mp4",
                         skipped_frames=0, total_frames=20)

    assert view._table.rowCount() == 2
    assert _vehicle_id_column_values(view) == [1, 2]
    assert view._table.isColumnHidden(_COL_PLATE_TEXT) is False
    assert view._table.isColumnHidden(_COL_CONFIDENCE) is False


def test_separate_rows_with_hidden_plate_columns_when_ocr_disabled(view):
    """With OCR off, every track is its own row and the plate columns are
    hidden (no plate text to merge on). (Req 14.4)"""
    # Four separate tracks, none merged because deduplication does not apply.
    tracks = [
        make_result(1, 0.0, 5.0),
        make_result(2, 1.0, 6.0),
        make_result(3, 2.0, 7.0),
        make_result(4, 3.0, 8.0),
    ]
    view.display_results(tracks, fps=1.0, ocr_enabled=False, output_path="out.mp4",
                         skipped_frames=0, total_frames=20)

    assert view._table.rowCount() == 4
    assert _vehicle_id_column_values(view) == [1, 2, 3, 4]
    assert view._table.isColumnHidden(_COL_PLATE_TEXT) is True
    assert view._table.isColumnHidden(_COL_CONFIDENCE) is True


# ----------------------------------------- summary from displayed rows (14.5)
def test_summary_computed_from_displayed_deduplicated_rows(view):
    """Total and wait statistics reflect exactly the rows displayed, i.e. the
    deduplicated set the view receives. (Req 14.5)"""
    # Suppose 5 raw tracks merged down to 3 deduplicated rows before display.
    deduped = [
        make_result(1, 0.0, 6.0, plate_text="ABC123", plate_confidence=0.9),   # wait 6.0
        make_result(2, 0.0, 12.0, plate_text="XYZ789", plate_confidence=0.8),  # wait 12.0
        make_result(3, 0.0, 3.0, plate_text="JKL456", plate_confidence=0.7),   # wait 3.0
    ]
    view.display_results(deduped, fps=1.0, ocr_enabled=True, output_path="out.mp4",
                         skipped_frames=0, total_frames=30)

    labels = view._summary_value_labels
    # Total counts the 3 displayed rows, not any pre-merge track count.
    assert labels["total_vehicles"].text() == "3"
    # Waits 6.0, 12.0, 3.0 -> avg 7.0, max 12.0, min 3.0.
    assert labels["avg_wait"].text() == "7.0"
    assert labels["max_wait"].text() == "12.0"
    assert labels["min_wait"].text() == "3.0"


# --------------------------------------------------- No_Output_Mode state (15.5)
def test_no_output_mode_hides_path_and_folder_and_shows_message(view):
    """When output_path is None, the path label, prefix, and open-folder button
    are hidden and the "No output video written" message is shown. (Req 15.5)"""
    results = [make_result(1, 0.0, 5.0)]
    view.display_results(results, fps=1.0, ocr_enabled=False, output_path=None,
                         skipped_frames=0, total_frames=10)

    # isHidden() reflects the explicit setVisible() flag regardless of whether
    # the (never-shown) top-level widget is realized on screen.
    assert view._output_prefix_label.isHidden() is True
    assert view._output_path_label.isHidden() is True
    assert view._open_folder_btn.isHidden() is True
    assert view._open_folder_btn.isEnabled() is False
    assert view._no_output_label.isHidden() is False
    assert view._no_output_label.text() == "No output video written"


def test_output_path_shown_when_output_written(view):
    """When an output path is provided, the path display and open-folder control
    are shown and the No_Output_Mode message is hidden. (Req 15.5)"""
    results = [make_result(1, 0.0, 5.0)]
    view.display_results(results, fps=1.0, ocr_enabled=False,
                         output_path="C:/out/annotated.mp4",
                         skipped_frames=0, total_frames=10)

    assert view._output_prefix_label.isHidden() is False
    assert view._output_path_label.isHidden() is False
    assert view._output_path_label.text() == "C:/out/annotated.mp4"
    assert view._open_folder_btn.isHidden() is False
    assert view._open_folder_btn.isEnabled() is True
    assert view._no_output_label.isHidden() is True


# ============================================================================
# Station display name in the results header
#
# Validates: Requirement 6.4
#
# set_station_display_name() shows the active Station_Display_Name in the
# results header (_station_header_label). An empty/whitespace value hides the
# label (default hidden state); a non-empty value is shown via the shared
# header_label() helper, truncating to 40 chars + "..." with the full value as
# the tooltip. The view is never realized on screen, so visibility is asserted
# via isVisibleTo(view) / the explicit isHidden() flag rather than isVisible().
# ============================================================================

from gui.station_validation import HEADER_DISPLAY_MAX_LEN


def test_station_display_name_shown_in_header(view):
    """A display name is shown in the results header label. (Req 6.4)"""
    view.set_station_display_name("Demo Inspection Station")

    assert view._station_header_label.isVisibleTo(view) is True
    assert view._station_header_label.isHidden() is False
    assert view._station_header_label.text() == "Demo Inspection Station"


def test_empty_station_display_name_hides_header(view):
    """An empty/whitespace display name hides the header label. (Req 6.4)"""
    # First show a value, then confirm a whitespace-only value hides it again.
    view.set_station_display_name("Demo Inspection Station")
    view.set_station_display_name("   ")

    assert view._station_header_label.text() == ""
    assert view._station_header_label.isVisibleTo(view) is False
    assert view._station_header_label.isHidden() is True


def test_long_station_display_name_truncated_with_full_tooltip(view):
    """A display name > 40 chars is truncated to 40 chars + '...' with the full
    value exposed as the tooltip. (Req 6.4, via header_label helper)"""
    long_name = "x" * (HEADER_DISPLAY_MAX_LEN + 15)  # 55 chars, > 40
    view.set_station_display_name(long_name)

    assert view._station_header_label.isVisibleTo(view) is True
    assert view._station_header_label.text() == long_name[:HEADER_DISPLAY_MAX_LEN] + "..."
    assert view._station_header_label.toolTip() == long_name
