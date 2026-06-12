"""Unit and property-based tests for ``StreamVideoSource`` (live-stream input).

These tests exercise ``gui.worker.StreamVideoSource`` without a real network
stream by monkeypatching ``cv2.VideoCapture`` (inside the worker module) with a
controllable fake capture that can fail reads on demand, and by stubbing
``time.sleep`` so reconnection retries do not block.

Covers:
- ``CAP_PROP_BUFFERSIZE`` set to 2 on open and on reconnect (low latency).
- Default FPS of 25.0 when the stream reports no valid frame rate.
- Stream metadata reports ``frame_count == -1`` (unknown length).
- Property 13: stream reconnection attempt counting.
- ``WorkerThread`` stream-mode behavior: ``connecting`` before the first frame
  (Req 11.13), ``reconnect_status`` on interruption (Req 11.8), finish with
  collected tracks on exhaustion (Req 11.9), indeterminate progress
  (``total == -1``, Req 11.6), VideoWriter skipped when output is disabled
  (Req 11.11, 15.4), and prompt "Stop" (Req 11.10).

Validates: Requirements 11.6, 11.8, 11.9, 11.10, 11.13, 15.4
"""

from __future__ import annotations

import time
import types

import cv2
import numpy as np
import pytest
import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from gui import worker as worker_module
from gui.models import ProcessingConfig, VideoMetadata
from gui.worker import StreamVideoSource, StreamLostError, WorkerThread


# ---------------------------------------------------------------------------
# Fake cv2.VideoCapture
# ---------------------------------------------------------------------------


class FakeVideoCapture:
    """Controllable stand-in for ``cv2.VideoCapture``.

    Records every ``set()`` call so tests can assert on capture properties
    (notably ``CAP_PROP_BUFFERSIZE``) and fails reads on demand.
    """

    def __init__(
        self,
        source: str,
        *,
        opened: bool = True,
        fps: float = 30.0,
        width: int = 1920,
        height: int = 1080,
        fail_reads: bool = False,
    ) -> None:
        self.source = source
        self._opened = opened
        self._fps = fps
        self._width = width
        self._height = height
        self._fail_reads = fail_reads
        self.props: dict[int, float] = {}
        self.released = False

    def set(self, prop: int, value: float) -> bool:
        self.props[prop] = value
        return True

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._height)
        return 0.0

    def isOpened(self) -> bool:  # noqa: N802 - mirror cv2 API
        return self._opened

    def read(self):
        if self._fail_reads:
            return False, None
        return True, np.zeros((self._height, self._width, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


@pytest.fixture
def fake_captures(monkeypatch):
    """Patch ``cv2.VideoCapture`` in the worker module and stub ``time.sleep``.

    Returns the list of constructed :class:`FakeVideoCapture` instances and
    allows per-test configuration of the kwargs passed to each new capture.
    """
    created: list[FakeVideoCapture] = []
    config: dict = {}

    def factory(source):
        cap = FakeVideoCapture(source, **config)
        created.append(cap)
        return cap

    monkeypatch.setattr(worker_module.cv2, "VideoCapture", factory)
    # Reconnection sleeps RECONNECT_INTERVAL_SECONDS between attempts; skip it.
    monkeypatch.setattr(worker_module.time, "sleep", lambda _seconds: None)

    return types_namespace(created=created, config=config)


def types_namespace(**kwargs):
    """Tiny attribute container (avoids importing types for a one-off)."""
    import types

    return types.SimpleNamespace(**kwargs)


# ---------------------------------------------------------------------------
# Unit tests: open / metadata behavior
# ---------------------------------------------------------------------------


class TestStreamOpenAndMetadata:
    def test_open_sets_buffersize_to_two(self, fake_captures) -> None:
        """Validates: Requirements 11.8 — low-latency capture buffer on open."""
        src = StreamVideoSource()
        assert src.open("rtsp://example.com/stream") is True

        cap = fake_captures.created[-1]
        assert cap.props.get(cv2.CAP_PROP_BUFFERSIZE) == 2

    def test_open_returns_false_when_capture_not_opened(self, fake_captures) -> None:
        """A capture that fails to open is reported as not opened."""
        fake_captures.config["opened"] = False
        src = StreamVideoSource()
        assert src.open("rtsp://example.com/stream") is False

    def test_default_fps_when_stream_reports_none(self, fake_captures) -> None:
        """Validates: Requirements 11.8 — FPS defaults to 25.0 for streams."""
        fake_captures.config["fps"] = 0.0  # stream reports no valid FPS
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        meta = src.get_metadata()
        assert meta.fps == 25.0
        assert meta.fps == StreamVideoSource.DEFAULT_STREAM_FPS

    def test_reported_fps_used_when_valid(self, fake_captures) -> None:
        """A valid stream FPS is carried through unchanged."""
        fake_captures.config["fps"] = 30.0
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        assert src.get_metadata().fps == 30.0

    def test_frame_count_is_unknown(self, fake_captures) -> None:
        """Validates: Requirements 11.8 — stream length is unknown (-1)."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        meta = src.get_metadata()
        assert meta.frame_count == -1
        assert meta.duration_seconds == 0.0

    def test_is_stream_true(self, fake_captures) -> None:
        """A live stream identifies itself as a stream source."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")
        assert src.is_stream() is True


# ---------------------------------------------------------------------------
# Property 13: Stream reconnection attempt counting
# ---------------------------------------------------------------------------


class TestReconnectionCounting:
    """Property 13: for k consecutive failures the reported attempt equals
    ``min(k, 5)``, and ``StreamLostError`` is signaled iff ``k > 5``.

    Validates: Requirements 11.8, 11.9
    """

    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(k=st.integers(min_value=0, max_value=25))
    def test_reconnect_attempt_counting(self, fake_captures, k) -> None:
        """Validates: Requirements 11.8, 11.9 — Property 13."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        reported: list[int] = []
        lost = False
        for _ in range(k):
            try:
                reported.append(src.reconnect())
            except StreamLostError:
                lost = True
                break

        max_attempts = StreamVideoSource.MAX_RECONNECT  # 5
        # Exhaustion (stream lost) iff more than MAX_RECONNECT failures.
        assert lost == (k > max_attempts)
        # Reported attempts are 1..min(k, MAX_RECONNECT) with no exhaustion case.
        assert reported == list(range(1, min(k, max_attempts) + 1))
        if reported:
            assert max(reported) == min(k, max_attempts)

    def test_attempts_one_through_five_succeed(self, fake_captures) -> None:
        """Validates: Requirements 11.8 — five attempts report 1..5."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        assert [src.reconnect() for _ in range(5)] == [1, 2, 3, 4, 5]

    def test_sixth_attempt_raises_stream_lost(self, fake_captures) -> None:
        """Validates: Requirements 11.9 — exhaustion after 5 attempts."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        for _ in range(5):
            src.reconnect()
        with pytest.raises(StreamLostError):
            src.reconnect()

    def test_reset_allows_counting_to_restart(self, fake_captures) -> None:
        """A successful read resets the counter so counting restarts at 1."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        assert src.reconnect() == 1
        assert src.reconnect() == 2
        src.reset_reconnect_attempts()
        assert src.reconnect() == 1

    def test_reconnect_restores_buffersize(self, fake_captures) -> None:
        """Validates: Requirements 11.8 — buffer stays small after reconnect."""
        src = StreamVideoSource()
        src.open("rtsp://example.com/stream")

        src.reconnect()
        cap = fake_captures.created[-1]
        assert cap.props.get(cv2.CAP_PROP_BUFFERSIZE) == 2


# ---------------------------------------------------------------------------
# WorkerThread stream-mode behavior
# ---------------------------------------------------------------------------
#
# These tests drive ``WorkerThread.run()`` in stream mode without a real
# network stream by patching :class:`StreamVideoSource` and
# :class:`PipelineAdapter` (in the worker module) with lightweight fakes.
# ``run()`` is invoked directly on the test thread for deterministic,
# synchronous signal capture (Qt uses DirectConnection when emitter and
# receiver share a thread); the "Stop" timing test starts a real background
# thread to measure stop latency.


def _frame(width: int = 8, height: int = 8) -> np.ndarray:
    """A small, valid BGR frame for QImage conversion."""
    return np.zeros((height, width, 3), dtype=np.uint8)


class FakeStreamSource:
    """Deterministic stream :class:`VideoSource` for WorkerThread tests.

    Yields ``good_frames`` successful reads (or an unbounded supply when
    ``infinite`` is True), then fails reads. On failure the worker calls
    :meth:`reconnect`, which counts attempts and raises
    :class:`StreamLostError` once ``max_reconnect`` is exceeded — mirroring the
    real :class:`StreamVideoSource` contract without sleeping or touching the
    network.
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
        self.read_calls = 0
        self.reconnect_calls = 0
        self.reset_calls = 0
        self.released = False

    def open(self, source: str) -> bool:
        self.opened_with = source
        return True

    def is_stream(self) -> bool:
        return True

    def get_metadata(self) -> VideoMetadata:
        # frame_count == -1 marks an unknown (indeterminate) stream length.
        return VideoMetadata(
            file_name=self.opened_with or "",
            file_path=self.opened_with or "",
            width=self._width,
            height=self._height,
            frame_count=-1,
            fps=self._fps,
            duration_seconds=0.0,
        )

    def read(self):
        self.read_calls += 1
        if self._infinite or self._good_remaining > 0:
            if not self._infinite:
                self._good_remaining -= 1
            return True, _frame(self._width, self._height)
        return False, None

    def reset_reconnect_attempts(self) -> None:
        self.reset_calls += 1
        self._reconnect_attempts = 0

    def reconnect(self) -> int:
        self._reconnect_attempts += 1
        self.reconnect_calls += 1
        if self._reconnect_attempts > self._max_reconnect:
            raise StreamLostError("stream lost (fake)")
        return self._reconnect_attempts

    def release(self) -> None:
        self.released = True


class FakeStreamAdapter:
    """PipelineAdapter stub returning canned per-frame results.

    Implements :meth:`finalize` (identity) so ``WorkerThread._emit_results``
    can build :class:`TrackResult` objects from the collected tracks.
    """

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
        # (annotated_frame, active_tracks, active_count)
        return frame.copy(), [], self._active_count

    def finalize(self, tracks: list) -> list:
        return tracks


def _stream_config(**overrides) -> ProcessingConfig:
    base = dict(
        video_path="",
        output_path=None,  # No_Output_Mode by default in these tests
        confidence=0.5,
        ocr_enabled=False,
        source_mode="stream",
        stream_url="rtsp://example.com/stream",
        no_output=True,
    )
    base.update(overrides)
    return ProcessingConfig(**base)


def _patch_stream(monkeypatch, source: FakeStreamSource,
                  adapter: FakeStreamAdapter) -> None:
    # ``run()`` constructs ``StreamVideoSource()`` and also reads the class
    # attribute ``StreamVideoSource.MAX_RECONNECT`` when emitting
    # ``reconnect_status``; the factory must expose it too.
    def factory():
        return source

    factory.MAX_RECONNECT = StreamVideoSource.MAX_RECONNECT
    monkeypatch.setattr(worker_module, "StreamVideoSource", factory)
    monkeypatch.setattr(
        worker_module, "PipelineAdapter", lambda config, fps=15.0: adapter
    )


class _RecordingVideoWriter:
    """Tracks whether ``cv2.VideoWriter`` was constructed, and write/release."""

    instances: list["_RecordingVideoWriter"] = []

    def __init__(self, *args) -> None:
        self.args = args
        self.writes = 0
        self.released = False
        _RecordingVideoWriter.instances.append(self)

    def write(self, frame) -> None:
        self.writes += 1

    def release(self) -> None:
        self.released = True


@pytest.fixture
def recording_writer(monkeypatch):
    """Patch ``cv2.VideoWriter`` / ``cv2.VideoWriter_fourcc`` in the worker."""
    _RecordingVideoWriter.instances = []
    monkeypatch.setattr(worker_module.cv2, "VideoWriter", _RecordingVideoWriter)
    monkeypatch.setattr(worker_module.cv2, "VideoWriter_fourcc", lambda *a: 0)
    return _RecordingVideoWriter


class TestWorkerStreamConnecting:
    """``connecting`` is emitted before the first stream frame (Req 11.13)."""

    def test_connecting_emitted_before_first_frame(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 11.13 — connecting precedes first frame."""
        source = FakeStreamSource(good_frames=2)
        adapter = FakeStreamAdapter()
        _patch_stream(monkeypatch, source, adapter)

        log: list[tuple[str, object]] = []
        thread = WorkerThread(_stream_config())
        thread.connecting.connect(lambda url: log.append(("connecting", url)))
        thread.frame_ready.connect(
            lambda img, idx, count: log.append(("frame", idx))
        )

        thread.run()  # synchronous: signals delivered via DirectConnection

        # The very first signal observed must be ``connecting``.
        assert log, "no signals were emitted"
        assert log[0] == ("connecting", "rtsp://example.com/stream")
        # And it carries the target stream URL, then frames follow.
        kinds = [entry[0] for entry in log]
        assert kinds.count("connecting") == 1
        first_frame_at = kinds.index("frame")
        assert first_frame_at > 0  # at least one connecting before any frame


class TestWorkerStreamReconnect:
    """``reconnect_status`` is emitted per attempt on interruption (Req 11.8)."""

    def test_reconnect_status_emitted_on_interruption(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 11.8 — attempt/max reported each retry."""
        # One good frame, then the stream fails: 5 reconnects (1..5) are
        # reported before the 6th attempt exhausts and raises StreamLostError.
        source = FakeStreamSource(good_frames=1, max_reconnect=5)
        adapter = FakeStreamAdapter()
        _patch_stream(monkeypatch, source, adapter)

        reconnects: list[tuple[int, int]] = []
        thread = WorkerThread(_stream_config())
        thread.reconnect_status.connect(
            lambda attempt, mx: reconnects.append((attempt, mx))
        )

        thread.run()

        assert reconnects == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


class TestWorkerStreamExhaustion:
    """On exhausted reconnection the worker finishes with collected tracks."""

    def test_finish_with_collected_tracks_on_exhaustion(
        self, qapp, monkeypatch
    ) -> None:
        """Validates: Requirements 11.9 — results reflect tracks collected."""
        collected = types.SimpleNamespace(
            vehicle_id=42,
            plate_text="",
            plate_confidence=0.0,
            first_frame=0,
            last_frame=2,
        )
        source = FakeStreamSource(good_frames=3, max_reconnect=5)
        adapter = FakeStreamAdapter(tracks=[collected])
        _patch_stream(monkeypatch, source, adapter)

        finished: list[list] = []
        errors: list[tuple] = []
        thread = WorkerThread(_stream_config())
        thread.processing_finished.connect(finished.append)
        thread.error.connect(lambda msg, idx: errors.append((msg, idx)))

        thread.run()

        # Completion (not error) fires, carrying the collected track(s).
        assert errors == []
        assert len(finished) == 1
        results = finished[0]
        assert len(results) == 1
        assert results[0].vehicle_id == 42
        # Stream resources are released on the way out.
        assert source.released is True


class TestWorkerStreamProgress:
    """Stream mode reports indeterminate progress (Req 11.6)."""

    def test_indeterminate_progress_total_is_minus_one(
        self, qapp, monkeypatch
    ) -> None:
        """Validates: Requirements 11.6 — total == -1 and no ETA for streams."""
        source = FakeStreamSource(good_frames=3, max_reconnect=5)
        adapter = FakeStreamAdapter(active_count=4)
        _patch_stream(monkeypatch, source, adapter)

        progress: list[tuple] = []
        thread = WorkerThread(_stream_config())
        thread.progress.connect(
            lambda cur, total, elapsed, active, eta:
            progress.append((cur, total, elapsed, active, eta))
        )

        thread.run()

        assert len(progress) == 3
        # Total frame count is unknown (-1) and ETA is suppressed (0.0).
        assert all(total == -1 for _cur, total, _e, _a, _eta in progress)
        assert all(eta == 0.0 for *_rest, eta in progress)
        # Processed count still increments; active count is propagated.
        assert [cur for cur, *_ in progress] == [1, 2, 3]
        assert all(active == 4 for *_h, active, _eta in progress)


class TestWorkerStreamOutput:
    """VideoWriter creation is gated by No_Output_Mode / output path (Req 15.4)."""

    def test_videowriter_skipped_when_no_output_true(
        self, qapp, monkeypatch, recording_writer
    ) -> None:
        """Validates: Requirements 15.4 — No_Output_Mode skips the writer."""
        source = FakeStreamSource(good_frames=2, max_reconnect=5)
        adapter = FakeStreamAdapter()
        _patch_stream(monkeypatch, source, adapter)

        # output_path set but no_output enabled -> writer must NOT be created.
        thread = WorkerThread(
            _stream_config(no_output=True, output_path="out.mp4")
        )
        thread.run()

        assert recording_writer.instances == []

    def test_videowriter_skipped_when_output_path_none(
        self, qapp, monkeypatch, recording_writer
    ) -> None:
        """Validates: Requirements 11.11, 15.4 — no path means no writer."""
        source = FakeStreamSource(good_frames=2, max_reconnect=5)
        adapter = FakeStreamAdapter()
        _patch_stream(monkeypatch, source, adapter)

        thread = WorkerThread(
            _stream_config(no_output=False, output_path=None)
        )
        thread.run()

        assert recording_writer.instances == []

    def test_videowriter_created_when_recording_enabled(
        self, qapp, monkeypatch, recording_writer
    ) -> None:
        """Validates: Requirements 11.11 — recording writes annotated frames."""
        source = FakeStreamSource(good_frames=2, max_reconnect=5)
        adapter = FakeStreamAdapter()
        _patch_stream(monkeypatch, source, adapter)

        thread = WorkerThread(
            _stream_config(no_output=False, output_path="out.mp4")
        )
        thread.run()

        # Exactly one writer is created and each processed frame is written.
        assert len(recording_writer.instances) == 1
        writer = recording_writer.instances[0]
        assert writer.writes == 2
        assert writer.released is True


class TestWorkerStreamStop:
    """The "Stop" control halts stream processing promptly (Req 11.10)."""

    def test_stop_stops_thread_within_time(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 11.10 — Stop halts within 3s, keeps tracks."""
        collected = types.SimpleNamespace(
            vehicle_id=7,
            plate_text="",
            plate_confidence=0.0,
            first_frame=0,
            last_frame=1,
        )
        # Unbounded stream so the loop only ends via cancellation.
        source = FakeStreamSource(infinite=True)
        adapter = FakeStreamAdapter(tracks=[collected], per_frame_delay=0.01)
        _patch_stream(monkeypatch, source, adapter)

        finished: list[list] = []
        thread = WorkerThread(_stream_config())
        # Direct connection so the slot runs in the worker thread (a plain
        # list append is GIL-safe), avoiding the need for a main-thread event
        # loop to deliver a queued cross-thread signal.
        from PySide6.QtCore import Qt

        thread.processing_finished.connect(
            finished.append, Qt.ConnectionType.DirectConnection
        )

        thread.start()
        time.sleep(0.1)  # let it process a few frames
        assert thread.isRunning()

        t0 = time.monotonic()
        thread.request_cancel()
        stopped = thread.wait(3000)  # ms
        elapsed = time.monotonic() - t0

        assert stopped, "stream worker did not stop after Stop"
        assert elapsed < 3.0, f"Stop took too long: {elapsed:.3f}s"
        # Stream "Stop" switches to results with the tracks collected so far.
        assert len(finished) == 1
        assert finished[0] and finished[0][0].vehicle_id == 7
        assert source.released is True
