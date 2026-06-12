"""Integration tests for the extension surface (Task 22.2).

These tests exercise the AWS Rekognition Detector_Backend, the AWS error
classification path, and the live-stream lifecycle end-to-end through the real
:class:`gui.worker.PipelineAdapter` / :class:`gui.worker.WorkerThread` and the
real :class:`gui.main_window.MainWindow` — while replacing only the true
external boundaries with lightweight fakes:

    * ``boto3.client`` is patched so :class:`detector_rekognition.RekognitionDetector`
      constructs and calls the Rekognition APIs **without any live AWS access**.
    * The live :class:`gui.worker.StreamVideoSource` is replaced by a
      deterministic fake that yields N frames then fails, so reconnection and
      "Stop" behavior can be driven without a network stream.

Covered flows:
    1. Rekognition selection + plate-text threading: the adapter constructs a
       ``RekognitionDetector`` for ``detector_backend="rekognition"`` and the
       plate text returned by Rekognition reaches the ``PlateTextAggregator``
       (Req 12.5).
    2. AWS error classification: ``NoCredentialsError`` is classified as a
       credentials error and a service ``ClientError`` as a region/service
       error, both returning to the Video_Input_Panel (Req 12.6, 12.7).
    3. Stream reconnection: indeterminate progress, ``reconnect_status``
       emissions, and finish-with-collected-tracks on exhaustion (Req 11.9).
    4. Stream "Stop": stops within 3 seconds and switches to the Results_View
       with the tracks collected so far (Req 11.10).

All tests run headless via the ``offscreen`` Qt platform (configured in
conftest.py).

Validates: Requirements 11.9, 11.10, 12.5, 12.6, 12.7
"""

from __future__ import annotations

import time
import types

import boto3
import numpy as np
import pytest
from botocore.exceptions import ClientError, NoCredentialsError

import gui.main_window as main_window_module
from gui import worker as worker_module
from gui.main_window import MainWindow
from gui.models import AppSettings, ProcessingConfig
from gui.worker import PipelineAdapter, StreamLostError, StreamVideoSource


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


def _frame(width: int = 400, height: int = 400) -> np.ndarray:
    """A valid BGR frame large enough for crop/feature extraction."""
    return np.zeros((height, width, 3), dtype=np.uint8)


class FakeSettings:
    """In-memory stand-in for SettingsManager (no disk access)."""

    def __init__(self, **overrides: object) -> None:
        self._settings = AppSettings(**overrides)

    def get(self) -> AppSettings:
        return self._settings

    def update(self, **kwargs: object) -> None:
        valid = {f.name for f in self._settings.__dataclass_fields__.values()}
        for key, value in kwargs.items():
            if key in valid:
                setattr(self._settings, key, value)

    def save(self) -> None:  # pragma: no cover - not exercised here
        pass

    @property
    def read_only(self) -> bool:
        return False


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


class _FakePath:
    """Path stand-in whose exists() is always True (model-check bypass)."""

    def __init__(self, *_args: object) -> None:
        pass

    def exists(self) -> bool:
        return True


def _bypass_start_validation(monkeypatch, window: MainWindow) -> None:
    """Make MainWindow.start_processing pass its preconditions (Req 8.1, 8.2)."""
    monkeypatch.setattr(main_window_module, "Path", _FakePath)
    monkeypatch.setattr(
        main_window_module, "resolve_model", lambda *a, **k: _FakePath("yolov8n.pt")
    )
    monkeypatch.setattr(window, "_output_path_writable", lambda _p: True)


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
    worker = getattr(win, "_worker", None)
    if worker is not None and worker.isRunning():
        worker.request_cancel()
        worker.wait(3000)
    win.deleteLater()


# ===========================================================================
# 1. Rekognition Detector_Backend: selection + plate-text threading (Req 12.5)
# ===========================================================================


class FakeRekognitionClient:
    """boto3 Rekognition client stand-in returning canned API responses.

    ``detect_labels`` reports one ``Car`` instance covering the central region
    of the frame; ``detect_text`` reports a single plate-like ``LINE`` whose
    geometry satisfies the detector's aspect/position filters, so the real
    :meth:`RekognitionDetector.detect` parses it into a ``plate_text`` without
    any live AWS call.
    """

    def __init__(self) -> None:
        self.detect_labels_calls = 0
        self.detect_text_calls = 0

    def detect_labels(self, **_kwargs):  # noqa: D401 - mirror boto3 API
        self.detect_labels_calls += 1
        return {
            "Labels": [
                {
                    "Name": "Car",
                    "Instances": [
                        {
                            "BoundingBox": {
                                "Left": 0.1,
                                "Top": 0.1,
                                "Width": 0.5,
                                "Height": 0.5,
                            },
                            "Confidence": 95.0,
                        }
                    ],
                }
            ]
        }

    def detect_text(self, **_kwargs):  # noqa: D401 - mirror boto3 API
        self.detect_text_calls += 1
        return {
            "TextDetections": [
                {
                    "Type": "LINE",
                    "DetectedText": "ABC123",
                    "Confidence": 92.0,
                    "Geometry": {
                        "BoundingBox": {
                            "Left": 0.2,
                            "Top": 0.6,
                            "Width": 0.5,
                            "Height": 0.12,
                        }
                    },
                }
            ]
        }


class _FakeTrack:
    """Minimal Tracked vehicle whose bbox matches a canned detection."""

    def __init__(self, vehicle_id: int, bbox: tuple[int, int, int, int]) -> None:
        self.vehicle_id = vehicle_id
        self.bbox = bbox
        self.plate_bbox = None
        self.visibility = 1.0
        self.frames_since_seen = 0
        self.plate_text = ""
        self.plate_confidence = 0.0

    def update_plate_text(self, text: str, conf: float) -> None:
        self.plate_text = text
        self.plate_confidence = conf


class _FakeTracker:
    """Deterministic tracker returning a fixed track list every update."""

    def __init__(self, tracks: list) -> None:
        self._tracks = tracks

    def update(self, _detections, _frame_idx, _features):
        return self._tracks

    def get_all_tracks(self) -> list:
        return self._tracks


@pytest.fixture
def patched_boto3(monkeypatch):
    """Patch ``boto3.client`` so RekognitionDetector never touches live AWS."""
    fake = FakeRekognitionClient()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    return fake


def _rekognition_config(**overrides) -> ProcessingConfig:
    base = dict(
        video_path="",
        output_path=None,
        confidence=0.5,
        ocr_enabled=True,
        detector_backend="rekognition",
        aws_region="us-east-1",
        no_output=True,
    )
    base.update(overrides)
    return ProcessingConfig(**base)


def test_adapter_selects_rekognition_backend(patched_boto3):
    """detector_backend="rekognition" builds a RekognitionDetector (Req 12.5)."""
    from detector_rekognition import RekognitionDetector

    adapter = PipelineAdapter(_rekognition_config(), fps=10.0)

    assert isinstance(adapter.detector, RekognitionDetector)
    # Plate reading enabled => an aggregator exists, but no local EasyOCR pass
    # is created for the Rekognition path (it reads text itself).
    assert adapter.text_aggregator is not None
    assert adapter.plate_ocr is None


def test_rekognition_detect_returns_canned_detections(patched_boto3):
    """The mocked client drives real detect() to canned detections (Req 12.5)."""
    adapter = PipelineAdapter(_rekognition_config(), fps=10.0)

    detections = adapter.detector.detect(_frame())

    assert patched_boto3.detect_labels_calls == 1
    assert len(detections) == 1
    det = detections[0]
    assert det["bbox"] == (40, 40, 240, 240)
    assert det["plate_text"] == "ABC123"
    assert det["plate_text_conf"] > 0.5


def test_rekognition_plate_text_threads_into_aggregator(patched_boto3):
    """Rekognition plate text reaches the aggregator + track (Req 12.5)."""
    adapter = PipelineAdapter(_rekognition_config(), fps=10.0)

    # Deterministically match the canned detection's vehicle box to a track.
    track = _FakeTrack(vehicle_id=7, bbox=(40, 40, 240, 240))
    adapter.tracker = _FakeTracker([track])

    frame = _frame()
    # Two frames so the aggregator clears its min_readings threshold (2).
    adapter.process_frame(frame, 0)
    adapter.process_frame(frame, 1)

    text, conf = adapter.text_aggregator.get_consensus(7)
    assert text == "ABC123"
    assert conf > 0.0
    # The consensus is threaded back onto the track for annotation/results.
    assert track.plate_text == "ABC123"
    # Rekognition's own text path was used (no separate EasyOCR pass).
    assert patched_boto3.detect_text_calls >= 1


# ===========================================================================
# 2. AWS error classification (Req 12.6, 12.7)
# ===========================================================================


def _worker_error_message(exc: Exception) -> str:
    """Reproduce the worker's error string format: ``"{Type}: {exc}"``."""
    return f"{type(exc).__name__}: {exc}"


def test_classify_no_credentials_error():
    """NoCredentialsError is classified as a credentials error (Req 12.6)."""
    msg = _worker_error_message(NoCredentialsError())

    title, body = MainWindow._classify_error(msg, frame_idx=3)

    assert title == "AWS credentials error"
    assert "credentials" in body.lower()


def test_classify_service_client_error():
    """A service ClientError is classified as a region/service error (Req 12.7)."""
    err = ClientError(
        {"Error": {"Code": "InvalidRegion", "Message": "bad region"}},
        "DetectLabels",
    )
    msg = _worker_error_message(err)

    title, body = MainWindow._classify_error(msg, frame_idx=12)

    assert title == "AWS Rekognition error"
    assert "region" in body.lower()


def test_on_worker_error_credentials_returns_to_input(window):
    """on_worker_error shows a dialog and returns to the input view (Req 12.6)."""
    msg = _worker_error_message(NoCredentialsError())

    window.on_worker_error(msg, frame_idx=0)

    assert FakeMessageBox.critical_calls, "expected an error dialog"
    title = FakeMessageBox.critical_calls[-1][0][1]
    assert title == "AWS credentials error"
    assert window.stack.currentIndex() == 0  # back on the input view


def test_on_worker_error_service_returns_to_input(window):
    """on_worker_error classifies service errors and returns to input (Req 12.7)."""
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "DetectLabels",
    )
    window.on_worker_error(_worker_error_message(err), frame_idx=5)

    assert FakeMessageBox.critical_calls
    title = FakeMessageBox.critical_calls[-1][0][1]
    assert title == "AWS Rekognition error"
    assert window.stack.currentIndex() == 0


# ===========================================================================
# 3 & 4. Live-stream lifecycle through MainWindow (Req 11.9, 11.10)
# ===========================================================================


class FakeStreamSource:
    """Deterministic stream VideoSource: yields frames then fails reads.

    Mirrors the real :class:`StreamVideoSource` reconnection contract — N good
    reads, then failures that drive :meth:`reconnect` until ``max_reconnect``
    is exceeded and :class:`StreamLostError` is raised — without sleeping or
    touching the network.
    """

    def __init__(
        self,
        *,
        good_frames: int = 0,
        infinite: bool = False,
        fps: float = 25.0,
        width: int = 8,
        height: int = 8,
        max_reconnect: int = StreamVideoSource.MAX_RECONNECT,
    ) -> None:
        self._good_remaining = good_frames
        self._infinite = infinite
        self._fps = fps
        self._width = width
        self._height = height
        self._max_reconnect = max_reconnect
        self._reconnect_attempts = 0
        self.opened_with: str | None = None
        self.released = False

    def open(self, source: str) -> bool:
        self.opened_with = source
        return True

    def is_stream(self) -> bool:
        return True

    def get_metadata(self):
        from gui.models import VideoMetadata

        return VideoMetadata(
            file_name=self.opened_with or "",
            file_path=self.opened_with or "",
            width=self._width,
            height=self._height,
            frame_count=-1,  # unknown length => indeterminate progress
            fps=self._fps,
            duration_seconds=0.0,
        )

    def read(self):
        if self._infinite or self._good_remaining > 0:
            if not self._infinite:
                self._good_remaining -= 1
            return True, np.zeros((self._height, self._width, 3), dtype=np.uint8)
        return False, None

    def reset_reconnect_attempts(self) -> None:
        self._reconnect_attempts = 0

    def reconnect(self) -> int:
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect:
            raise StreamLostError("stream lost (fake)")
        return self._reconnect_attempts

    def release(self) -> None:
        self.released = True


class FakeStreamAdapter:
    """PipelineAdapter stub returning canned per-frame results."""

    def __init__(
        self,
        *,
        active_count: int = 1,
        tracks: list | None = None,
        per_frame_delay: float = 0.0,
    ) -> None:
        self._active_count = active_count
        self._tracks = tracks if tracks is not None else []
        self._delay = per_frame_delay
        self.tracker = types.SimpleNamespace(get_all_tracks=lambda: self._tracks)

    def process_frame(self, frame: np.ndarray, frame_idx: int):
        if self._delay:
            time.sleep(self._delay)
        return frame.copy(), [], self._active_count

    def finalize(self, tracks: list) -> list:
        return tracks


def _collected_vehicle(vehicle_id: int):
    """A minimal TrackedVehicle stand-in for build_track_result()."""
    return types.SimpleNamespace(
        vehicle_id=vehicle_id,
        plate_text="",
        plate_confidence=0.0,
        first_frame=0,
        last_frame=2,
    )


def _patch_stream(monkeypatch, source: FakeStreamSource, adapter: FakeStreamAdapter):
    """Replace the worker's stream boundary with the supplied fakes."""

    def factory():
        return source

    # run() reads StreamVideoSource.MAX_RECONNECT to emit reconnect_status.
    factory.MAX_RECONNECT = StreamVideoSource.MAX_RECONNECT
    monkeypatch.setattr(worker_module, "StreamVideoSource", factory)
    monkeypatch.setattr(
        worker_module, "PipelineAdapter", lambda config, fps=15.0: adapter
    )


def _stream_config(**overrides) -> ProcessingConfig:
    base = dict(
        video_path="",
        output_path=None,
        confidence=0.5,
        ocr_enabled=False,
        source_mode="stream",
        stream_url="rtsp://example.com/stream",
        no_output=True,
    )
    base.update(overrides)
    return ProcessingConfig(**base)


def test_stream_reconnect_then_finish_with_collected_tracks(
    window, qapp, monkeypatch
):
    """Exhausted reconnection finishes on the Results_View (Req 11.8, 11.9).

    The fake stream yields three frames, then fails: the worker reports five
    reconnection attempts (1..5) before the sixth exhausts and the GUI switches
    to the Results_View showing the track collected before the interruption.

    Validates: Requirements 11.8, 11.9
    """
    source = FakeStreamSource(good_frames=3, max_reconnect=5)
    adapter = FakeStreamAdapter(tracks=[_collected_vehicle(42)])
    _patch_stream(monkeypatch, source, adapter)
    _bypass_start_validation(monkeypatch, window)

    # Record reconnection attempts as they reach the ProcessingView slot.
    reconnects: list[tuple[int, int]] = []
    original = window.processing_view.on_reconnect_status

    def _recording(attempt: int, mx: int) -> None:
        reconnects.append((attempt, mx))
        original(attempt, mx)

    window.processing_view.on_reconnect_status = _recording

    window.start_processing(_stream_config())

    # Indeterminate progress: the bar is in the busy (range 0..0) state.
    assert window.processing_view.progress_bar.maximum() == 0

    assert window._worker is not None
    assert window._worker.wait(5000), "stream worker did not finish in time"

    switched = _pump_until(
        qapp, lambda: window.windowTitle() == "Opus LaneSight - Results"
    )
    assert switched, "did not switch to results after stream loss"

    # Five reconnection attempts were reported (1..5) before exhaustion.
    assert reconnects == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    # Results reflect the track collected before the interruption.
    assert window.stack.currentIndex() == 2
    assert window.results_view._table.rowCount() == 1
    assert source.released is True


def test_stream_stop_switches_to_results_within_time(window, qapp, monkeypatch):
    """The "Stop" control halts within 3s and shows results (Req 11.10).

    Validates: Requirements 11.10
    """
    source = FakeStreamSource(infinite=True)
    adapter = FakeStreamAdapter(tracks=[_collected_vehicle(7)], per_frame_delay=0.01)
    _patch_stream(monkeypatch, source, adapter)
    _bypass_start_validation(monkeypatch, window)

    window.start_processing(_stream_config())

    assert window._worker is not None
    assert _pump_until(
        qapp,
        lambda: window._worker.isRunning()
        and window.processing_view.current_frame_value.text() != "0",
        timeout=3.0,
    ), "stream worker did not start processing frames"
    assert window.stack.currentIndex() == 1  # processing view active

    # Request "Stop" via the processing view's signal path.
    t0 = time.monotonic()
    window.processing_view.cancel_requested.emit()
    stopped = window._worker.wait(3000)
    elapsed = time.monotonic() - t0

    assert stopped, "stream worker did not stop after Stop"
    assert elapsed < 3.0, f"Stop took too long: {elapsed:.3f}s"

    switched = _pump_until(
        qapp, lambda: window.windowTitle() == "Opus LaneSight - Results"
    )
    assert switched, "Stop did not switch to results"
    assert window.stack.currentIndex() == 2
    assert window.results_view._table.rowCount() == 1
    assert source.released is True
