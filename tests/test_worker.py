"""Unit tests for WorkerThread signal emission and lifecycle.

These tests exercise ``gui.worker.WorkerThread`` without GPU, YOLO models, or
real video files by monkeypatching :class:`FileVideoSource` and
:class:`PipelineAdapter` with lightweight fakes. ``run()`` is invoked directly
on the test thread for deterministic, synchronous signal capture (Qt delivers
signals via DirectConnection when emitter and receiver share a thread); the
cancellation-timing test starts a real background thread to measure stop
latency.

Validates: Requirements 3.1, 3.6, 3.7, 6.5, 6.6
"""

from __future__ import annotations

import time
import types

import numpy as np
import pytest

from gui.models import ProcessingConfig
from gui import worker as worker_module
from gui.worker import WorkerThread


def _frame() -> np.ndarray:
    """A small, valid BGR frame for QImage conversion."""
    return np.zeros((8, 8, 3), dtype=np.uint8)


class FakeVideoSource:
    """Deterministic VideoSource: yields a fixed number of frames then EOF."""

    def __init__(self, frame_count: int, width: int = 8, height: int = 8,
                 fps: float = 10.0, infinite: bool = False) -> None:
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
            duration_seconds=self._frame_count / self._fps,
        )

    def release(self) -> None:
        self.released = True


class FakePipelineAdapter:
    """PipelineAdapter stub returning canned per-frame results."""

    def __init__(self, active_count: int = 2, raise_on_frame: int | None = None,
                 per_frame_delay: float = 0.0) -> None:
        self._active_count = active_count
        self._raise_on_frame = raise_on_frame
        self._per_frame_delay = per_frame_delay
        self.tracker = types.SimpleNamespace(get_all_tracks=lambda: [])

    def process_frame(self, frame: np.ndarray, frame_idx: int):
        if self._raise_on_frame is not None and frame_idx == self._raise_on_frame:
            raise RuntimeError("boom")
        if self._per_frame_delay:
            time.sleep(self._per_frame_delay)
        # (annotated_frame, active_tracks, active_count)
        return frame.copy(), [], self._active_count

    def finalize(self, tracks: list) -> list:
        # Identity finalize: mirrors PipelineAdapter.finalize's no-op path
        # (plate dedup disabled) so WorkerThread._emit_results can call it.
        return tracks


def _make_config(**overrides) -> ProcessingConfig:
    base = dict(
        video_path="fake.mp4",
        output_path="",  # empty => no cv2.VideoWriter, no disk I/O
        confidence=0.5,
        ocr_enabled=False,
    )
    base.update(overrides)
    return ProcessingConfig(**base)


def _patch_pipeline(monkeypatch, source: FakeVideoSource,
                    adapter: FakePipelineAdapter) -> None:
    monkeypatch.setattr(worker_module, "FileVideoSource", lambda: source)
    monkeypatch.setattr(
        worker_module, "PipelineAdapter", lambda config, fps=15.0: adapter
    )


class TestFrameReadySignal:
    """frame_ready carries the annotated QImage, frame index, and track count."""

    def test_frame_ready_emitted_per_frame(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 3.1, 6.5 — one frame_ready per processed frame."""
        from PySide6.QtGui import QImage

        source = FakeVideoSource(frame_count=3)
        adapter = FakePipelineAdapter(active_count=2)
        _patch_pipeline(monkeypatch, source, adapter)

        emitted: list[tuple] = []
        thread = WorkerThread(_make_config())
        thread.frame_ready.connect(
            lambda img, idx, count: emitted.append((img, idx, count))
        )

        thread.run()  # synchronous: signals delivered via DirectConnection

        assert len(emitted) == 3
        # frame indices are sequential starting at 0
        assert [idx for _img, idx, _count in emitted] == [0, 1, 2]
        # track count matches the adapter's canned active_count
        assert all(count == 2 for _img, _idx, count in emitted)
        # payload is a valid, non-null QImage of the frame dimensions
        for img, _idx, _count in emitted:
            assert isinstance(img, QImage)
            assert not img.isNull()
            assert img.width() == 8 and img.height() == 8


class TestProgressSignal:
    """progress reports processed/total/elapsed/active/eta with correct values."""

    def test_progress_values(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 3.6 — progress reflects frames processed."""
        source = FakeVideoSource(frame_count=3)
        adapter = FakePipelineAdapter(active_count=2)
        _patch_pipeline(monkeypatch, source, adapter)

        progress: list[tuple] = []
        thread = WorkerThread(_make_config())
        thread.progress.connect(
            lambda cur, total, elapsed, active, eta:
            progress.append((cur, total, elapsed, active, eta))
        )

        thread.run()

        assert len(progress) == 3
        # processed count increments 1..3, total stays at frame_count
        assert [p[0] for p in progress] == [1, 2, 3]
        assert all(p[1] == 3 for p in progress)
        # active count propagated; elapsed and eta are non-negative
        assert all(p[3] == 2 for p in progress)
        assert all(p[2] >= 0.0 for p in progress)
        assert all(p[4] >= 0.0 for p in progress)
        # eta reaches 0 on the final frame (no remaining frames)
        assert progress[-1][4] == 0.0

    def test_processing_finished_emitted_on_normal_completion(
        self, qapp, monkeypatch
    ) -> None:
        """Validates: Requirements 3.6 — completion signal fires at end of stream."""
        source = FakeVideoSource(frame_count=2)
        adapter = FakePipelineAdapter()
        _patch_pipeline(monkeypatch, source, adapter)

        finished: list[list] = []
        thread = WorkerThread(_make_config())
        thread.processing_finished.connect(finished.append)

        thread.run()

        assert len(finished) == 1
        assert finished[0] == []  # no tracks from the stub tracker


class TestErrorSignal:
    """error fires with message and frame index on pipeline exceptions."""

    def test_error_emitted_on_pipeline_exception(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 3.7, 6.5 — pipeline exception surfaces as error."""
        source = FakeVideoSource(frame_count=3)
        adapter = FakePipelineAdapter(raise_on_frame=0)
        _patch_pipeline(monkeypatch, source, adapter)

        errors: list[tuple] = []
        finished: list[list] = []
        thread = WorkerThread(_make_config())
        thread.error.connect(lambda msg, idx: errors.append((msg, idx)))
        thread.processing_finished.connect(finished.append)

        thread.run()

        assert len(errors) == 1
        msg, frame_idx = errors[0]
        assert "RuntimeError" in msg and "boom" in msg
        assert frame_idx == 0
        # completion signal must NOT fire when processing fails
        assert finished == []

    def test_error_emitted_when_video_cannot_open(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 3.7 — failure to open source reports an error."""
        source = FakeVideoSource(frame_count=1)
        monkeypatch.setattr(source, "open", lambda src: False)
        adapter = FakePipelineAdapter()
        _patch_pipeline(monkeypatch, source, adapter)

        errors: list[tuple] = []
        thread = WorkerThread(_make_config(video_path="missing.mp4"))
        thread.error.connect(lambda msg, idx: errors.append((msg, idx)))

        thread.run()

        assert len(errors) == 1
        assert "Cannot open video file" in errors[0][0]


class TestCancellation:
    """request_cancel stops the worker promptly and suppresses completion."""

    def test_cancel_stops_thread_quickly(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 3.6, 6.6 — cancellation stops within ~1s."""
        # Infinite source so the loop only ends via cancellation.
        source = FakeVideoSource(frame_count=0, infinite=True)
        adapter = FakePipelineAdapter(active_count=1, per_frame_delay=0.01)
        _patch_pipeline(monkeypatch, source, adapter)

        finished: list[list] = []
        thread = WorkerThread(_make_config())
        thread.processing_finished.connect(finished.append)

        thread.start()
        # Let it process a few frames before cancelling.
        time.sleep(0.1)
        assert thread.isRunning()

        t0 = time.monotonic()
        thread.request_cancel()
        stopped = thread.wait(3000)  # ms
        elapsed = time.monotonic() - t0

        assert stopped, "Worker thread did not stop after cancellation"
        assert elapsed < 1.0, f"Cancellation took too long: {elapsed:.3f}s"
        # No completion results when cancelled mid-stream.
        assert finished == []
        assert source.released is True

    def test_cancel_before_run_emits_nothing(self, qapp, monkeypatch) -> None:
        """Validates: Requirements 6.6 — pre-cancelled run does no frame work."""
        source = FakeVideoSource(frame_count=5)
        adapter = FakePipelineAdapter()
        _patch_pipeline(monkeypatch, source, adapter)

        emitted: list = []
        finished: list = []
        thread = WorkerThread(_make_config())
        thread.frame_ready.connect(lambda *a: emitted.append(a))
        thread.processing_finished.connect(finished.append)

        thread.request_cancel()
        thread.run()

        assert emitted == []
        assert finished == []
        assert thread.is_cancelled is True
