"""Unit tests for :class:`gui.processing_view.ProcessingView`.

Exercises the slots that update the progress bar, the formatted statistics
labels, and the skipped-frame counter without a display server (the ``qapp``
fixture forces the offscreen Qt platform). Also covers the module-level
``format_duration`` helper used to render elapsed time and ETA.

Validates: Requirements 3.4, 3.5, 8.3
"""

from __future__ import annotations

import pytest

from gui.processing_view import ProcessingView, format_duration


@pytest.fixture()
def view(qapp):
    """Provide a fresh ProcessingView for each test."""
    return ProcessingView()


# --------------------------------------------------------------- progress bar
def test_on_progress_updates_progress_bar_value(view):
    """Progress bar reflects current/total as a percentage. (Req 3.4)"""
    view.on_progress(50, 100, 75.0, 3, 75.0)
    assert view.progress_bar.value() == 50


def test_on_progress_updates_frame_and_count_labels(view):
    """Current/total frame and active vehicle labels update. (Req 3.4, 3.5)"""
    view.on_progress(50, 100, 75.0, 3, 75.0)
    assert view.current_frame_value.text() == "50"
    assert view.total_frames_value.text() == "100"
    assert view.active_count_value.text() == "3"


# --------------------------------------------------------- stats time labels
def test_on_progress_formats_elapsed_and_eta(view):
    """Elapsed time and ETA labels render as mm:ss. (Req 3.5)"""
    view.on_progress(50, 100, 75.0, 3, 75.0)
    assert view.elapsed_value.text() == "01:15"
    assert view.eta_value.text() == "01:15"


def test_format_duration_minutes_seconds():
    """75 seconds formats as mm:ss."""
    assert format_duration(75) == "01:15"


def test_format_duration_hours():
    """3725 seconds formats as H:MM:SS once an hour or longer."""
    assert format_duration(3725) == "1:02:05"


def test_format_duration_negative_is_zero():
    """Negative input is treated as zero. (Req 3.5)"""
    assert format_duration(-5) == "00:00"


# ------------------------------------------------------------- error counter
def test_on_frame_error_updates_counter(view):
    """Skipped frame counter reflects the reported error count. (Req 8.3)"""
    view.on_frame_error(4)
    assert view.error_value.text() == "4"
