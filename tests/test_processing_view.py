"""Unit tests for :class:`gui.processing_view.ProcessingView`.

Exercises the slots that update the progress bar, the formatted statistics
labels, and the skipped-frame counter without a display server (the ``qapp``
fixture forces the offscreen Qt platform). Also covers the module-level
``format_duration`` helper used to render elapsed time and ETA.

Validates: Requirements 3.4, 3.5, 8.3, 11.6, 11.8, 11.13
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


# ----------------------------------------------------------- stream behaviour
def test_on_progress_indeterminate_when_total_unknown(view):
    """total == -1 switches the progress bar to indeterminate. (Req 11.6)"""
    view.on_progress(120, -1, 30.0, 4, 0.0)
    # Indeterminate mode is signalled by a (0, 0) range on QProgressBar.
    assert view.progress_bar.minimum() == 0
    assert view.progress_bar.maximum() == 0


def test_on_progress_indeterminate_updates_live_stats(view):
    """Live stream stats show frame, active count, elapsed and FPS. (Req 11.6)"""
    view.on_progress(120, -1, 30.0, 4, 0.0)
    assert view.current_frame_value.text() == "120"
    assert view.active_count_value.text() == "4"
    assert view.elapsed_value.text() == "00:30"
    # Effective FPS = current / elapsed = 120 / 30 = 4.0
    assert view.eta_value.text() == "4.0"


def test_set_stream_mode_uses_indeterminate_progress(view):
    """Enabling stream mode puts the progress bar in indeterminate state. (Req 11.6)"""
    view.set_stream_mode(True)
    assert view.progress_bar.minimum() == 0
    assert view.progress_bar.maximum() == 0


def test_on_connecting_status_text_shows_url(view):
    """Connecting status text includes the stream URL. (Req 11.13)"""
    url = "rtsp://camera.local/stream1"
    view.on_connecting(url)
    assert view.status_label.text() == f"Connecting to {url}…"
    # isHidden() reflects the explicit visibility flag even when the top-level
    # widget is never shown (offscreen test harness).
    assert not view.status_label.isHidden()


def test_on_reconnect_status_text_format(view):
    """Reconnect status text shows attempt out of max. (Req 11.8)"""
    view.on_reconnect_status(2, 5)
    assert view.status_label.text() == "Reconnecting (2/5)…"
    assert not view.status_label.isHidden()


def test_stop_button_label_in_stream_mode(view):
    """Cancel button is relabelled "Stop" in stream mode. (Req 11.6)"""
    view.set_stream_mode(True)
    assert view.cancel_button.text() == "Stop"


def test_cancel_button_label_default_in_file_mode(view):
    """Cancel button reads "Cancel" in file mode (default)."""
    assert view.cancel_button.text() == "Cancel"
    view.set_stream_mode(True)
    view.set_stream_mode(False)
    assert view.cancel_button.text() == "Cancel"
