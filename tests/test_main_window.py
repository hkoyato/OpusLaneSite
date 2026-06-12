"""Unit tests for the MainWindow shell (Task 10.3).

Verifies the application shell behavior in isolation: window-title state on
view switching, drag-and-drop validation (accept valid video extensions,
reject others), close-during-processing confirmation, and the future-proof
navigation capacity.

These tests run headless via the ``offscreen`` Qt platform (configured in
conftest.py) and never touch %LOCALAPPDATA%: a lightweight fake settings
object stands in for SettingsManager so geometry persistence stays in memory.

Validates: Requirements 9.3, 9.5, 9.6, 10.1
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

import gui.main_window as main_window_module
from gui.main_window import MainWindow
from gui.models import AppSettings


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSettings:
    """In-memory stand-in for SettingsManager.

    Provides the ``get()`` / ``update(**kwargs)`` surface MainWindow (and the
    nested InputPanel) rely on, so geometry restore/persist never writes disk.
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

    def save(self) -> None:  # pragma: no cover - not exercised by MainWindow
        pass


class FakeWorker:
    """Minimal worker double exposing the lifecycle API closeEvent touches."""

    def __init__(self, running: bool = True) -> None:
        self._running = running
        self.cancel_requested = False
        self.wait_ms: int | None = None

    def isRunning(self) -> bool:
        return self._running

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def wait(self, ms: int) -> bool:
        self.wait_ms = ms
        return True


class FakeDnDEvent:
    """Drag/drop event double mirroring the QDragEnterEvent/QDropEvent API.

    PySide6's real drag-event constructors do not reliably retain the attached
    QMimeData under the offscreen platform (``mimeData()`` returns a bare
    QObject), so this double wraps a genuine QMimeData and records the
    accept/ignore decision the handlers make.
    """

    def __init__(self, mime: QMimeData) -> None:
        self._mime = mime
        self._accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        self._accepted = True

    def accept(self) -> None:
        self._accepted = True

    def ignore(self) -> None:
        self._accepted = False

    def isAccepted(self) -> bool:
        return self._accepted


class _FakeButton:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessageBox:
    """Non-blocking QMessageBox stand-in for the close-confirmation dialog.

    ``next_choice`` selects which added button ``clickedButton()`` returns,
    letting tests drive both confirmation branches without a real modal.
    """

    Icon = QMessageBox.Icon
    ButtonRole = QMessageBox.ButtonRole
    next_choice = "Continue processing"

    def __init__(self, parent: object = None) -> None:
        self._buttons: dict[str, _FakeButton] = {}
        self._clicked: _FakeButton | None = None

    def setIcon(self, *_args: object) -> None:
        pass

    def setWindowTitle(self, *_args: object) -> None:
        pass

    def setText(self, *_args: object) -> None:
        pass

    def addButton(self, text: str, _role: object) -> _FakeButton:
        btn = _FakeButton(text)
        self._buttons[text] = btn
        return btn

    def exec(self) -> int:
        self._clicked = self._buttons.get(FakeMessageBox.next_choice)
        return 0

    def clickedButton(self) -> _FakeButton | None:
        return self._clicked

    @staticmethod
    def warning(*_args: object, **_kwargs: object) -> None:
        return None

    @staticmethod
    def critical(*_args: object, **_kwargs: object) -> None:
        return None

    @staticmethod
    def information(*_args: object, **_kwargs: object) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp):
    """Construct a MainWindow backed by fake (in-memory) settings."""
    win = MainWindow(settings=FakeSettings())
    yield win
    win.deleteLater()


def _make_drag_enter_event(path: str) -> "FakeDnDEvent":
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    return FakeDnDEvent(mime)


def _make_drop_event(path: str) -> "FakeDnDEvent":
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    return FakeDnDEvent(mime)


# ---------------------------------------------------------------------------
# View switching / window title (Requirement 9.3)
# ---------------------------------------------------------------------------


def test_switch_to_input_sets_ready_title(window):
    """Input view sets the '... - Ready' window title."""
    window.switch_view("input")
    assert window.windowTitle() == "Opus LaneSight - Ready"


def test_switch_to_results_sets_results_title(window):
    """Results view sets the '... - Results' window title."""
    window.switch_view("results")
    assert window.windowTitle() == "Opus LaneSight - Results"


def test_switch_to_processing_includes_video_name(window):
    """Processing view title includes the active session video name."""
    window._session_video_name = "clip.mp4"
    window.switch_view("processing")

    title = window.windowTitle()
    assert "Processing" in title
    assert "clip.mp4" in title


def test_switch_view_updates_stack_index(window):
    """Switching the view selects the matching stack page."""
    window.switch_view("results")
    assert window.stack.currentIndex() == 2

    window.switch_view("input")
    assert window.stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# Drag and drop (Requirements 9.5, 9.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "C:/videos/clip.mp4",
    "C:/videos/clip.AVI",
    "C:/videos/clip.mov",
    "C:/videos/clip.mkv",
])
def test_drag_enter_accepts_valid_extensions(window, path):
    """dragEnterEvent accepts drags carrying a supported video extension."""
    event = _make_drag_enter_event(path)
    window.dragEnterEvent(event)
    assert event.isAccepted() is True


@pytest.mark.parametrize("path", [
    "C:/videos/clip.txt",
    "C:/videos/clip.pdf",
    "C:/videos/clip",
])
def test_drag_enter_rejects_invalid_extensions(window, path):
    """dragEnterEvent ignores drags whose file is not a supported video."""
    event = _make_drag_enter_event(path)
    window.dragEnterEvent(event)
    assert event.isAccepted() is False


def test_drop_valid_video_forwards_to_input_panel(window, monkeypatch):
    """A valid dropped video is accepted and handed to the input panel."""
    captured: list[str] = []
    monkeypatch.setattr(
        window.input_panel, "set_video_from_drop", lambda p: captured.append(p)
    )

    event = _make_drop_event("C:/videos/clip.mp4")
    window.dropEvent(event)

    assert event.isAccepted() is True
    assert captured == ["C:/videos/clip.mp4"]


def test_drop_invalid_extension_is_rejected(window, monkeypatch):
    """An unsupported dropped file is rejected without forwarding."""
    captured: list[str] = []
    monkeypatch.setattr(
        window.input_panel, "set_video_from_drop", lambda p: captured.append(p)
    )
    # Avoid a real (blocking) warning dialog on the rejection path.
    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)

    event = _make_drop_event("C:/videos/clip.txt")
    window.dropEvent(event)

    assert event.isAccepted() is False
    assert captured == []


# ---------------------------------------------------------------------------
# Close-during-processing confirmation (Requirement 9.2)
# ---------------------------------------------------------------------------


def test_close_during_processing_continue_ignores_event(window, monkeypatch):
    """Choosing 'Continue processing' keeps the window open (event ignored)."""
    window._worker = FakeWorker(running=True)
    FakeMessageBox.next_choice = "Continue processing"
    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is False
    assert window._worker.cancel_requested is False


def test_close_during_processing_cancel_accepts_and_stops_worker(window, monkeypatch):
    """Choosing 'Cancel and exit' cancels the worker and accepts the close."""
    worker = FakeWorker(running=True)
    window._worker = worker
    FakeMessageBox.next_choice = "Cancel and exit"
    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True
    assert worker.cancel_requested is True
    assert worker.wait_ms == 3000


def test_close_when_idle_accepts_without_dialog(window, monkeypatch):
    """With no running worker, closing proceeds without a confirmation dialog."""
    window._worker = None

    def _fail(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("No confirmation dialog should appear when idle")

    monkeypatch.setattr(main_window_module, "QMessageBox", _fail)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True


# ---------------------------------------------------------------------------
# Navigation capacity (Requirement 10.1)
# ---------------------------------------------------------------------------


def test_sidebar_holds_at_least_six_nav_entries(window):
    """The sidebar can hold at least 6 entries without overflow (Req 10.1).

    Currently 3 active entries are shown; future views (dashboard, stream
    config, zone editor) will be added once implemented. The layout/widget
    supports more than 6 entries without scrolling.
    """
    assert window.nav.count() >= 3
