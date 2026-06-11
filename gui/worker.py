"""Worker module: video source abstractions and pipeline execution thread."""

from __future__ import annotations

import io
import os
import sys
import time
from collections import deque
from threading import Event
from typing import Callable, Protocol

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from gui.models import ProcessingConfig, VideoMetadata
from gui.utils import build_track_result


class VideoSource(Protocol):
    """Abstract video input — file today, RTSP/RTMP in future."""

    def open(self, source: str) -> bool: ...

    def read(self) -> tuple[bool, np.ndarray | None]: ...

    def get_metadata(self) -> VideoMetadata: ...

    def release(self) -> None: ...


class FileVideoSource:
    """cv2.VideoCapture wrapper implementing VideoSource for local files."""

    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._source: str = ""

    def open(self, source: str) -> bool:
        """Open a local video file. Returns True if successfully opened."""
        self._source = source
        self._cap = cv2.VideoCapture(source)
        return self._cap.isOpened()

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Read the next frame. Returns (success, frame)."""
        if self._cap is None:
            return False, None
        ret, frame = self._cap.read()
        if not ret:
            return False, None
        return True, frame

    def get_metadata(self) -> VideoMetadata:
        """Return VideoMetadata extracted from the opened video file."""
        if self._cap is None:
            return VideoMetadata(
                file_name="",
                file_path="",
                width=0,
                height=0,
                frame_count=0,
                fps=0.0,
                duration_seconds=0.0,
            )
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        duration_seconds = frame_count / fps if fps > 0 else 0.0
        return VideoMetadata(
            file_name=os.path.basename(self._source),
            file_path=self._source,
            width=width,
            height=height,
            frame_count=frame_count,
            fps=fps,
            duration_seconds=duration_seconds,
        )

    def release(self) -> None:
        """Release the underlying VideoCapture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class PipelineAdapter:
    """Adapts GUI ProcessingConfig to pipeline module initialization.

    Bridges the GUI configuration to the existing pipeline modules
    (VehicleDetector, VehicleTracker, AppearanceExtractor, and optionally
    PlateOCR/PlateTextAggregator) without modifying their source. Constructor
    parameters mirror the names/types used by ``process_video`` in ``main.py``.

    The video FPS is required to size the tracker's time-based parameters
    exactly as ``main.py`` does (``max_lost = int(fps * 4)`` and
    ``gallery_max_age = int(fps * 30)``). When unknown, a sensible default of
    15 FPS is used.
    """

    def __init__(self, config: ProcessingConfig, fps: float = 15.0) -> None:
        # Lazy imports keep heavy pipeline dependencies (ultralytics/torch,
        # easyocr) out of GUI module import time and out of headless tests.
        from detector import VehicleDetector
        from tracker import VehicleTracker
        from appearance import AppearanceExtractor

        from gui.assets import resolve_model_str

        self.config = config
        self.fps = fps if fps and fps > 0 else 15.0
        self.ocr_interval = config.ocr_interval

        self.detector = VehicleDetector(
            vehicle_model_path=resolve_model_str(),
            plate_model_path=config.plate_model_path,
            confidence=config.confidence,
        )

        self.tracker = VehicleTracker(
            iou_threshold=0.3,
            max_lost=int(self.fps * 4),         # Keep tracks alive 4s during occlusion
            min_hits=3,
            appearance_weight=0.4,
            reid_threshold=0.45,                 # Re-ID sensitivity
            gallery_max_age=int(self.fps * 30),  # Keep in gallery up to 30s
        )

        self.appearance_extractor = AppearanceExtractor(feature_dim=128)

        self.plate_ocr = None
        self.text_aggregator = None
        if config.ocr_enabled:
            from ocr import PlateOCR, PlateTextAggregator

            self.plate_ocr = PlateOCR(languages=config.ocr_languages, gpu=True)
            self.text_aggregator = PlateTextAggregator(
                min_readings=3, agreement_threshold=0.4
            )

    def process_frame(
        self, frame: np.ndarray, frame_idx: int
    ) -> tuple[np.ndarray, list, int]:
        """Process a single frame through the full pipeline.

        Mirrors the per-frame flow of ``process_video`` in ``main.py``:
        detect -> appearance features -> track -> periodic OCR -> annotate.

        Returns
        -------
        tuple
            ``(annotated_frame, active_tracks, active_count)`` where
            ``active_count`` counts tracks currently visible
            (``frames_since_seen == 0``).
        """
        # Detect vehicles and plates
        detections = self.detector.detect(frame)

        # Extract appearance features for all detections
        features = None
        if detections:
            bboxes = [d["bbox"] for d in detections]
            features = self.appearance_extractor.extract_batch(frame, bboxes)

        # Update tracker with detections and features
        active_tracks = self.tracker.update(detections, frame_idx, features)

        # Run OCR on plate regions periodically with multi-frame voting
        if self.plate_ocr and frame_idx % self.ocr_interval == 0:
            for track in active_tracks:
                if track.frames_since_seen == 0 and track.plate_bbox is not None:
                    text, conf = self.plate_ocr.read_plate(frame, track.plate_bbox)
                    if text:
                        self.text_aggregator.add_reading(
                            track.vehicle_id, text, conf
                        )
                    # Update track with consensus text
                    consensus_text, consensus_conf = self.text_aggregator.get_consensus(
                        track.vehicle_id
                    )
                    if consensus_text:
                        track.update_plate_text(consensus_text, consensus_conf)

        # Draw annotations on a copy to preserve the original frame
        annotated_frame = self._draw_annotations(frame.copy(), active_tracks)

        # Count currently visible vehicles
        active_count = sum(
            1 for t in active_tracks if t.frames_since_seen == 0
        )

        return annotated_frame, active_tracks, active_count

    @staticmethod
    def _draw_annotations(frame: np.ndarray, tracks: list) -> np.ndarray:
        """Draw bounding boxes, IDs, and plate text on the frame.

        Replicates ``draw_annotations`` from ``main.py`` so the GUI preview
        and output video match the CLI output without importing the CLI entry
        point.
        """
        for track in tracks:
            if track.frames_since_seen > 0:
                continue

            x1, y1, x2, y2 = track.bbox
            # Vehicle box (green)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Label with ID and plate text
            label = f"ID:{track.vehicle_id}"
            if track.plate_text:
                label += f" [{track.plate_text}]"
            cv2.putText(
                frame, label, (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
            )

            # Plate box (blue)
            if track.plate_bbox is not None:
                px1, py1, px2, py2 = track.plate_bbox
                cv2.rectangle(frame, (px1, py1), (px2, py2), (255, 0, 0), 2)
                plate_label = track.plate_text if track.plate_text else "Plate"
                cv2.putText(
                    frame, plate_label, (px1, py1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1,
                )

        return frame


class QueueIO(io.TextIOBase):
    """Thread-safe-ish IO wrapper that emits complete lines via a callback.

    Used by :class:`WorkerThread` to redirect ``sys.stdout`` / ``sys.stderr``
    while the pipeline runs so console output reaches the GUI log panel
    instead of a background console window. Partial writes are buffered until
    a newline is seen; :meth:`flush` emits any trailing partial line.
    """

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> int:
        """Buffer *text* and emit each complete (newline-terminated) line."""
        if not isinstance(text, str):
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._callback(line)
        return len(text)

    def flush(self) -> None:
        """Emit any buffered partial line."""
        if self._buffer:
            self._callback(self._buffer)
            self._buffer = ""


class WorkerThread(QThread):
    """Background pipeline execution thread.

    Runs the full detection/tracking/OCR pipeline off the GUI thread and
    communicates exclusively through Qt signals. Cancellation is cooperative
    via a :class:`threading.Event` checked once per frame, so the loop stops
    within roughly one frame (well under one second at normal frame rates).

    Note
    ----
    The completion signal is named ``processing_finished`` rather than
    ``finished`` to avoid shadowing :class:`QThread`'s built-in ``finished``
    signal (which takes no arguments). ``processing_finished`` carries the
    ``list[TrackResult]`` produced for the session.
    """

    # Signals
    frame_ready = Signal(QImage, int, int)          # annotated frame, frame_idx, active_tracks
    progress = Signal(int, int, float, int, float)  # current, total, elapsed, active, eta
    frame_error = Signal(int)                        # cumulative error count
    processing_finished = Signal(list)               # list[TrackResult]
    error = Signal(str, int)                         # error message, frame_idx
    log_output = Signal(str)                         # captured stdout/stderr line

    # Maximum number of log lines retained in memory.
    MAX_LOG_LINES = 10_000
    # Abort processing after this many consecutive frame-read failures.
    MAX_CONSECUTIVE_FAILURES = 100

    def __init__(self, config: ProcessingConfig) -> None:
        super().__init__()
        self.config = config
        self._cancel_event = Event()
        self._log_buffer: deque[str] = deque(maxlen=self.MAX_LOG_LINES)
        self._error_count = 0

    def request_cancel(self) -> None:
        """Request cooperative cancellation (thread-safe).

        Sets the cancellation Event. ``run()`` checks this once per frame and
        stops promptly (within one frame iteration).
        """
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._cancel_event.is_set()

    def _record_log(self, line: str) -> None:
        """Retain *line* in the bounded buffer and emit it to listeners."""
        self._log_buffer.append(line)
        self.log_output.emit(line)

    @staticmethod
    def _to_qimage(frame_bgr: np.ndarray) -> QImage:
        """Convert an annotated BGR ``np.ndarray`` to an RGB :class:`QImage`.

        Returns a deep-copied QImage so it does not alias the temporary numpy
        buffer once this method returns.
        """
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        height, width, channels = rgb.shape
        bytes_per_line = channels * width
        image = QImage(
            rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
        )
        return image.copy()

    def run(self) -> None:
        """Main processing loop — detect, track, OCR, emit signals per frame.

        Redirects stdout/stderr to the log panel, opens the video source,
        processes frames through :class:`PipelineAdapter`, writes annotated
        frames to the output video, and emits per-frame and completion signals.
        Handles cancellation, frame-read failures, and pipeline exceptions.
        """
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        queue_io = QueueIO(self._record_log)
        sys.stdout = queue_io
        sys.stderr = queue_io

        source = FileVideoSource()
        writer: cv2.VideoWriter | None = None
        frame_idx = 0

        try:
            if not source.open(self.config.video_path):
                self.error.emit(
                    f"Cannot open video file: {self.config.video_path}", 0
                )
                return

            metadata: VideoMetadata = source.get_metadata()
            fps = metadata.fps if metadata.fps and metadata.fps > 0 else 15.0
            total_frames = metadata.frame_count

            adapter = PipelineAdapter(self.config, fps=fps)

            if self.config.output_path:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(
                    self.config.output_path,
                    fourcc,
                    fps,
                    (metadata.width, metadata.height),
                )

            start_time = time.monotonic()
            consecutive_failures = 0

            while not self._cancel_event.is_set():
                ret, frame = source.read()

                if not ret or frame is None:
                    # Distinguish normal end-of-stream from mid-stream failure.
                    if total_frames <= 0 or frame_idx >= total_frames:
                        break  # Normal completion.

                    consecutive_failures += 1
                    self._error_count += 1
                    self.frame_error.emit(self._error_count)
                    frame_idx += 1

                    if consecutive_failures > self.MAX_CONSECUTIVE_FAILURES:
                        self.error.emit(
                            "Aborted: exceeded "
                            f"{self.MAX_CONSECUTIVE_FAILURES} consecutive "
                            "frame-read failures (video may be corrupt).",
                            frame_idx,
                        )
                        return
                    continue

                consecutive_failures = 0

                annotated_frame, _active_tracks, active_count = adapter.process_frame(
                    frame, frame_idx
                )

                if writer is not None:
                    writer.write(annotated_frame)

                self.frame_ready.emit(
                    self._to_qimage(annotated_frame), frame_idx, active_count
                )

                processed = frame_idx + 1
                elapsed = time.monotonic() - start_time
                if processed > 0 and total_frames > 0:
                    remaining = max(0, total_frames - processed)
                    eta = (elapsed / processed) * remaining
                else:
                    eta = 0.0
                self.progress.emit(
                    processed, total_frames, elapsed, active_count, eta
                )

                frame_idx += 1

            if self._cancel_event.is_set():
                return

            # Build final results from all confirmed tracks.
            all_tracks = adapter.tracker.get_all_tracks()
            results = [
                build_track_result(track, fps, total_frames)
                for track in all_tracks
            ]
            self.processing_finished.emit(results)

        except Exception as exc:  # noqa: BLE001 - report any pipeline failure
            self.error.emit(f"{type(exc).__name__}: {exc}", frame_idx)
        finally:
            if writer is not None:
                writer.release()
            source.release()
            queue_io.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
