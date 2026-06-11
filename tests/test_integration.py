"""Integration tests for the Opus LaneSight GUI (Task 11.1).

Exercises the full GUI wiring end-to-end with the real
:class:`gui.main_window.MainWindow`, the real :class:`gui.worker.WorkerThread`
(running on a genuine background QThread), and the real views — while the
heavyweight pipeline boundary is replaced by lightweight fakes
(``FileVideoSource`` / ``PipelineAdapter``) so no GPU, YOLO model, or video
file is required.

Covered flows:
    1. Full processing flow: start -> worker signals -> ProcessingView updates
       -> finished -> ResultsView populated and view switched to results.
    2. Cancellation flow: start (infinite source) -> cancel -> thread stops ->
       return to the input view.
    3. Error flow: pipeline raises -> error signal -> error dialog -> input view.
    4. Settings persistence: real SettingsManager round-trips on disk.

All tests run headless via the ``offscreen`` Qt platform (configured in
conftest.py). Queued cross-thread signals are delivered by pumping the event
loop with ``qapp.processEvents()`` after joining the worker with ``wait()``,
which keeps synchronization deterministic and non-flaky.

Validates: Requirements 3.1, 3.6, 3.7, 6.5, 6.6, 5.2
"""

from __future__ import annotations

import time
import types

import numpy as np
import pytest

import gui.main_window as main_window_module
from gui import worker as worker_module
from gui.main_window import MainWindow
from gui.models import AppSettings, ProcessingConfig
from gui.settings import SettingsManager


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _frame() -> np.ndarray:
    """A small, valid BGR frame for QImage conversion."""
    return np.zeros((8, 8, 3), dtype=np.uint8)


class FakeSettings:
    """In-memory stand-in for SettingsManager (no disk access)."""

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

    def save(self) -> None:  # pragma: no cover - not exercised here
        pass

    @property
    def read_only(self) -> bool:
        return False


class FakeVideoSource:
    """Deterministic VideoSource: yields a fixed number of frames then EOF."""

    def __init__(
        self,
        frame_count: int,
        width: int = 8,
        height: int = 8,
        fps: float = 10.0,
        infinite: bool = False,
    ) -> None:
        self._frame_count = frame_count
        self._width = width
        self._height = height
        self._fps = fps
        self._infinite = infinite
        self._read_calls = 0
        self.released = False

    def open(self, source: str) -> bool:
        return True

    def read(self):
        if self._infinite:
            return True, _frame()
        if self._read_calls < self._frame_count:
            self._read_calls += 1
            return True, _frame()
        return False, None

    def get_metadata(self):
        from gui.models import VideoMetadata

        return VideoMetadata(
            file_name="fake.mp4",
            file_path="fake.mp4",
            width=self._width,
            height=self._height,
            frame_count=self._frame_count,
            fps=self._fps,
            duration_seconds=(
                self._frame_count / self._fps if self._fps else 0.0
            ),
        )

    def release(self) -> None:
        self.released = True


def _fake_vehicle(
    vehicle_id: int = 1, first_frame: int = 0, last_frame: int = 2,
    plate_text: str = "", plate_confidence: float = 0.0,
):
    """A minimal TrackedVehicle stand-in for build_track_result()."""
    return types.SimpleNamespace(
        vehicle_id=vehicle_id,
        plate_text=plate_text,
        plate_confidence=plate_confidence,
        first_frame=first_frame,
        last_frame=last_frame,
    )


class FakePipelineAdapter:
    """PipelineAdapter stub returning canned per-frame results."""

    def __init__(
        self,
        active_count: int = 2,
        raise_on_frame: int | None = None,
        per_frame_delay: float = 0.0,
        tracks: list | None = None,
    ) -> None:
        self._active_count = active_count
        self._raise_on_frame = raise_on_frame
        self._per_frame_delay = per_frame_delay
        canned = tracks if tracks is not None else []
        self.tracker = types.SimpleNamespace(get_all_tracks=lambda: canned)

    def process_frame(self, frame: np.ndarray, frame_idx: int):
        if self._raise_on_frame is not None and frame_idx == self._raise_on_frame:
            raise RuntimeError("boom")
        if self._per_frame_delay:
            time.sleep(self._per_frame_delay)
        return frame.copy(), [], self._active_count


class FakeMessageBox:
    """Non-blocking QMessageBox stand-in that records dialog invocations."""

    critical_calls: list[tuple] = []
    information_calls: list[tuple] = []
    warning_calls: list[tuple] = []

    @classmethod
    def reset(cls) -> None:
        cls.critical_calls = []
        cls.information_calls = []
        cls.warning_calls = []

    @classmethod
    def critical(cls, *args: object, **kwargs: object) -> None:
        cls.critical_calls.append((args, kwargs))

    @classmethod
    def information(cls, *args: object, **kwargs: object) -> None:
        cls.information_calls.append((args, kwargs))

    @classmethod
    def warning(cls, *args: object, **kwargs: object) -> None:
        cls.warning_calls.append((args, kwargs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_pipeline(
    monkeypatch, source: FakeVideoSource, adapter: FakePipelineAdapter
) -> None:
    """Replace the worker's pipeline boundary with the supplied fakes."""
    monkeypatch.setattr(worker_module, "FileVideoSource", lambda: source)
    monkeypatch.setattr(
        worker_module, "PipelineAdapter", lambda config, fps=15.0: adapter
    )


class _FakePath:
    """Path stand-in whose exists() is always True (model-check bypass)."""

    def __init__(self, *_args: object) -> None:
        pass

    def exists(self) -> bool:
        return True


def _bypass_start_validation(monkeypatch, window: MainWindow) -> None:
    """Make MainWindow.start_processing pass its preconditions.

    Bypasses the YOLO model existence check (Requirement 8.1) and the
    output-path writability check (Requirement 8.2) so the worker launches
    under the fakes without touching the filesystem.
    """
    monkeypatch.setattr(main_window_module, "Path", _FakePath)
    monkeypatch.setattr(
        main_window_module, "resolve_model", lambda *a, **k: _FakePath("yolov8n.pt")
    )
    monkeypatch.setattr(window, "_output_path_writable", lambda _p: True)


def _make_config(**overrides) -> ProcessingConfig:
    base = dict(
        video_path="fake.mp4",
        output_path="",  # empty => no cv2.VideoWriter, no disk I/O
        confidence=0.5,
        ocr_enabled=False,
    )
    base.update(overrides)
    return ProcessingConfig(**base)


def _pump_until(qapp, predicate, timeout: float = 5.0) -> bool:
    """Pump the Qt event loop until *predicate* is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


@pytest.fixture
def window(qapp, monkeypatch):
    """A MainWindow backed by fake settings, with dialogs stubbed out."""
    FakeMessageBox.reset()
    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)
    win = MainWindow(settings=FakeSettings())
    yield win
    # Ensure no worker outlives the test.
    worker = getattr(win, "_worker", None)
    if worker is not None and worker.isRunning():
        worker.request_cancel()
        worker.wait(3000)
    win.deleteLater()


# ---------------------------------------------------------------------------
# 1. Full processing flow
# ---------------------------------------------------------------------------


def test_full_processing_flow_populates_results(window, qapp, monkeypatch):
    """start -> worker signals -> ProcessingView updates -> ResultsView shown.

    Validates: Requirements 3.1, 3.6, 6.5
    """
    source = FakeVideoSource(frame_count=5, fps=10.0)
    adapter = FakePipelineAdapter(
        active_count=2,
        tracks=[_fake_vehicle(vehicle_id=1, first_frame=0, last_frame=2)],
    )
    _patch_pipeline(monkeypatch, source, adapter)
    _bypass_start_validation(monkeypatch, window)

    window.start_processing(_make_config())

    # The worker runs on a real background thread; join it, then pump the
    # event loop to deliver all queued cross-thread signals.
    assert window._worker is not None
    assert window._worker.wait(5000), "worker thread did not finish in time"

    switched = _pump_until(
        qapp, lambda: window.windowTitle() == "Opus LaneSight - Results"
    )
    assert switched, "view did not switch to results after completion"

    # ProcessingView received progress + frame updates before completion.
    assert window.processing_view.progress_bar.value() > 0
    assert int(window.processing_view.current_frame_value.text()) > 0
    assert not window.processing_view.frame_label.pixmap().isNull()

    # ResultsView is populated and showing the table (not the empty state).
    assert window.stack.currentIndex() == 2
    assert window.results_view._table.rowCount() == 1
    assert window.results_view._content_stack.currentIndex() == 0
    assert window.results_view._summary_value_labels["total_vehicles"].text() == "1"
    # Video resources were released.
    assert source.released is True


# ---------------------------------------------------------------------------
# 2. Cancellation flow
# ---------------------------------------------------------------------------


def test_cancellation_flow_returns_to_input(window, qapp, monkeypatch):
    """start (infinite source) -> cancel -> thread stops -> input view.

    Validates: Requirements 6.6
    """
    source = FakeVideoSource(frame_count=0, infinite=True)
    adapter = FakePipelineAdapter(active_count=1, per_frame_delay=0.01)
    _patch_pipeline(monkeypatch, source, adapter)
    _bypass_start_validation(monkeypatch, window)

    window.start_processing(_make_config(video_path="clip.mp4"))

    # Let the worker process a few frames so we cancel mid-stream.
    assert _pump_until(
        qapp, lambda: window.processing_view.progress_bar.value() >= 0
        and window._worker.isRunning(), timeout=2.0
    )
    assert window.stack.currentIndex() == 1  # processing view active
    time.sleep(0.05)

    # Request cancellation via the processing view's signal path.
    window.processing_view.cancel_requested.emit()

    t0 = time.monotonic()
    stopped = window._worker.wait(3000)
    elapsed = time.monotonic() - t0
    assert stopped, "worker did not stop after cancellation"
    assert elapsed < 3.0

    # Pump events so the QThread.finished handler returns us to input.
    assert _pump_until(
        qapp, lambda: window.windowTitle() == "Opus LaneSight - Ready"
    )
    assert window.stack.currentIndex() == 0
    assert source.released is True
    # A cancellation confirmation was shown.
    assert FakeMessageBox.information_calls


# ---------------------------------------------------------------------------
# 3. Error flow
# ---------------------------------------------------------------------------


def test_error_flow_shows_dialog_and_returns_to_input(window, qapp, monkeypatch):
    """pipeline raises -> error signal -> error dialog -> input view.

    Validates: Requirements 3.7, 6.5
    """
    source = FakeVideoSource(frame_count=3, fps=10.0)
    adapter = FakePipelineAdapter(raise_on_frame=0)
    _patch_pipeline(monkeypatch, source, adapter)
    _bypass_start_validation(monkeypatch, window)

    window.start_processing(_make_config())

    assert window._worker.wait(5000), "worker thread did not finish in time"

    returned = _pump_until(
        qapp, lambda: window.windowTitle() == "Opus LaneSight - Ready"
    )
    assert returned, "did not return to input view after error"
    assert window.stack.currentIndex() == 0

    # An error dialog was shown and results were never populated.
    assert FakeMessageBox.critical_calls, "expected an error dialog"
    assert window.results_view._table.rowCount() == 0


# ---------------------------------------------------------------------------
# 4. Settings persistence (real SettingsManager, on disk)
# ---------------------------------------------------------------------------


def test_settings_round_trip_on_disk(tmp_path, monkeypatch):
    """Modified settings persist and reload identically from disk.

    Validates: Requirements 5.2
    """
    config_dir = tmp_path / "OpusLaneSight"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(SettingsManager, "CONFIG_FILE", config_file)

    mgr = SettingsManager()
    mgr.update(
        confidence=0.8,
        ocr_enabled=True,
        ocr_language="en",
        ocr_interval=25,
        output_path=str(tmp_path / "out.mp4"),
        window_width=1400,
        window_height=900,
        window_x=120,
        window_y=64,
    )
    mgr.save()  # deterministic write (bypasses the debounce timer)

    assert config_file.exists()

    # A fresh manager reading the same file must observe identical values.
    fresh = SettingsManager()
    reloaded = fresh.get()
    assert reloaded.confidence == pytest.approx(0.8)
    assert reloaded.ocr_enabled is True
    assert reloaded.ocr_language == "en"
    assert reloaded.ocr_interval == 25
    assert reloaded.output_path == str(tmp_path / "out.mp4")
    assert reloaded.window_width == 1400
    assert reloaded.window_height == 900
    assert reloaded.window_x == 120
    assert reloaded.window_y == 64
