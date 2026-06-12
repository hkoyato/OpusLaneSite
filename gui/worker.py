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
from gui.utils import build_track_result, deduplicate_by_plate


class StreamLostError(Exception):
    """Raised when a live stream cannot be re-established after the maximum
    number of reconnection attempts (Req 11.9)."""


class VideoSource(Protocol):
    """Abstract video input — local file or live RTSP/RTMP/HTTP stream."""

    def open(self, source: str) -> bool: ...

    def read(self) -> tuple[bool, np.ndarray | None]: ...

    def get_metadata(self) -> VideoMetadata: ...

    def is_stream(self) -> bool: ...

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

    def is_stream(self) -> bool:
        """Return False — a local file has a known, finite frame count."""
        return False

    def release(self) -> None:
        """Release the underlying VideoCapture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class StreamVideoSource:
    """cv2.VideoCapture wrapper for RTSP/RTMP/HTTP live streams (Req 11).

    Mirrors the backend stream handling in ``main.py`` without importing it:

    - ``cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)`` on open to minimize latency.
    - Defaults FPS to 25.0 when the stream does not report one.
    - ``get_metadata()`` reports ``frame_count = -1`` (unknown) so the
      ``WorkerThread`` drives an indeterminate progress indicator.
    - :meth:`reconnect` releases and re-opens the capture on read failure,
      retrying up to :attr:`MAX_RECONNECT` times at
      :attr:`RECONNECT_INTERVAL_SECONDS` intervals, raising
      :class:`StreamLostError` once attempts are exhausted (Req 11.9).

    ``is_stream()`` returns True so the ``WorkerThread`` selects the
    indeterminate-progress and reconnection behavior.
    """

    # Maximum reconnection attempts before the stream is declared lost.
    MAX_RECONNECT = 5
    # Seconds to wait between reconnection attempts.
    RECONNECT_INTERVAL_SECONDS = 2
    # Default FPS assumed when a stream does not report a valid frame rate.
    DEFAULT_STREAM_FPS = 25.0

    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._source: str = ""
        self._reconnect_attempts = 0

    def open(self, source: str) -> bool:
        """Open the live stream. Returns True if successfully opened.

        Reduces the capture buffer to two frames to minimize latency, exactly
        as the backend does for stream input.
        """
        self._source = source
        self._cap = cv2.VideoCapture(source)
        # Reduce buffer to minimize latency on live streams.
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
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
        """Return VideoMetadata for the stream.

        ``frame_count`` is ``-1`` (unknown) and ``duration_seconds`` is ``0.0``
        because a live stream has no finite length. FPS defaults to
        :attr:`DEFAULT_STREAM_FPS` when the stream reports none.
        """
        if self._cap is None:
            return VideoMetadata(
                file_name="",
                file_path=self._source,
                width=0,
                height=0,
                frame_count=-1,
                fps=self.DEFAULT_STREAM_FPS,
                duration_seconds=0.0,
            )
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        if fps is None or fps <= 0:
            fps = self.DEFAULT_STREAM_FPS  # Stream did not report a valid FPS.
        return VideoMetadata(
            file_name=self._source,
            file_path=self._source,
            width=width,
            height=height,
            frame_count=-1,
            fps=fps,
            duration_seconds=0.0,
        )

    def is_stream(self) -> bool:
        """Return True — a live stream has an unknown, unbounded frame count."""
        return True

    def reset_reconnect_attempts(self) -> None:
        """Reset the reconnection counter after a successful read."""
        self._reconnect_attempts = 0

    def reconnect(self) -> int:
        """Attempt one reconnection after a read failure.

        Increments the attempt counter, then releases and re-opens the
        capture (restoring the reduced buffer size). Returns the current
        attempt number (1..:attr:`MAX_RECONNECT`). Raises
        :class:`StreamLostError` once more than :attr:`MAX_RECONNECT`
        consecutive failures have occurred (Req 11.9).
        """
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self.MAX_RECONNECT:
            raise StreamLostError(
                f"Stream lost after {self.MAX_RECONNECT} reconnection "
                f"attempts: {self._source}"
            )

        time.sleep(self.RECONNECT_INTERVAL_SECONDS)

        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(self._source)
        # Restore the reduced buffer to keep latency low after reconnecting.
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

        return self._reconnect_attempts

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
        # easyocr, boto3) out of GUI module import time and out of headless
        # tests.
        from tracker import VehicleTracker
        from appearance import AppearanceExtractor

        from gui.assets import ensure_model, resolve_model_str

        self.config = config
        self.fps = fps if fps and fps > 0 else 15.0
        self.ocr_interval = config.ocr_interval
        # Detection interval (Req 13): detect only on frames where
        # ``frame_idx % detect_interval == 0``; the tracker's Kalman filter
        # predicts on the skipped frames.
        self.detect_interval = config.detect_interval

        # Select the detector backend (Req 12). Rekognition is a cloud
        # alternative to local YOLOv8; it can also read plate text itself,
        # gated on whether plate reading is enabled (config.ocr_enabled).
        if config.detector_backend == "rekognition":
            from detector_rekognition import RekognitionDetector

            self.detector = RekognitionDetector(
                region_name=config.aws_region,
                confidence=config.confidence,
                use_rekognition_text=config.ocr_enabled,
            )
        else:
            from detector import VehicleDetector

            # Ensure the model is present (auto-download if missing), falling
            # back to the bare name so Ultralytics can self-resolve.
            ensure_model()
            self.detector = VehicleDetector(
                vehicle_model_path=resolve_model_str(),
                plate_model_path=config.plate_model_path,
                confidence=config.confidence,
            )

        # Adaptive controller for Rekognition cost optimization
        self.adaptive = None
        if getattr(config, "auto_adjust", False) and config.detector_backend == "rekognition":
            from adaptive import AdaptiveController
            self.adaptive = AdaptiveController(
                min_interval=1,
                max_interval=int(self.fps * 2),
                min_resolution=640,
                max_resolution=1920,
                sensitivity=0.5,
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

        # Plate-reading setup (only when plate reading is enabled).
        #   - YOLO backend: EasyOCR reads plates, with a voting aggregator.
        #   - Rekognition backend: Rekognition reads plate text itself, so no
        #     EasyOCR is created; an aggregator votes on the Rekognition text
        #     (mirrors main.py, which uses min_readings=2 for this path).
        self.plate_ocr = None
        self.text_aggregator = None
        if config.ocr_enabled:
            from ocr import PlateTextAggregator

            if config.detector_backend == "rekognition":
                self.text_aggregator = PlateTextAggregator(
                    min_readings=2, agreement_threshold=0.4
                )
            else:
                from ocr import PlateOCR

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
        Detection runs only on frames where
        ``frame_idx % detect_interval == 0``; on skipped frames the tracker is
        updated with no detections so its Kalman filter predicts forward.

        Returns
        -------
        tuple
            ``(annotated_frame, active_tracks, active_count)`` where
            ``active_count`` counts tracks currently visible
            (``frames_since_seen == 0``).
        """
        # Detect on interval frames only; predict via Kalman on skipped frames.
        if self.adaptive:
            # Adaptive mode: controller decides when to detect
            should_detect = self.adaptive.should_detect(frame_idx)
            # Dynamically adjust Rekognition upload resolution
            if hasattr(self.detector, "max_image_dimension"):
                self.detector.max_image_dimension = self.adaptive.get_resolution()
        else:
            should_detect = (frame_idx % self.detect_interval == 0)

        if should_detect:
            detections = self.detector.detect(frame)

            # Extract appearance features for all detections
            features = None
            if detections:
                bboxes = [d["bbox"] for d in detections]
                features = self.appearance_extractor.extract_batch(frame, bboxes)

            # Update tracker with detections and features
            active_tracks = self.tracker.update(detections, frame_idx, features)

            # Feed Rekognition plate text directly into the aggregator
            # (mirrors main.py; avoids a separate EasyOCR pass).
            if self.text_aggregator and self.config.detector_backend == "rekognition":
                for det in detections:
                    plate_text = det.get("plate_text")
                    plate_conf = det.get("plate_text_conf", 0.0)
                    if plate_text and plate_conf > 0.5:
                        # Find the matching track for this detection.
                        for track in active_tracks:
                            if track.bbox == det["bbox"] or (
                                track.plate_bbox == det.get("plate_bbox")
                                and track.plate_bbox is not None
                            ):
                                self.text_aggregator.add_reading(
                                    track.vehicle_id, plate_text, plate_conf,
                                    track.visibility,
                                )
                                break
        else:
            # No detection this frame — tracker predicts using Kalman.
            active_tracks = self.tracker.update([], frame_idx, None)

        # Update adaptive controller with current scene state
        if self.adaptive:
            self.adaptive.update(active_tracks)

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
        elif self.text_aggregator:
            # Still update consensus on non-OCR frames (Rekognition may have
            # added readings on this or a previous detection frame).
            for track in active_tracks:
                if track.frames_since_seen == 0:
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

    def finalize(self, tracks: list) -> list:
        """Apply plate-based deduplication to the final track list.

        Delegates to :func:`gui.utils.deduplicate_by_plate`, which mirrors
        ``main._deduplicate_by_plate`` via the unmodified ``plate_utils``
        helpers. Deduplication is applied only when plate reading is enabled
        (``config.ocr_enabled``); otherwise *tracks* is returned unchanged.

        Validates: Requirements 14.1, 14.2, 14.3, 14.4
        """
        return deduplicate_by_plate(tracks, self.config.ocr_enabled)

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
    progress = Signal(int, int, float, int, float)  # current, total(-1 if stream), elapsed, active, eta
    connecting = Signal(str)                          # stream_url, before the first frame (Req 11.13)
    reconnect_status = Signal(int, int)               # attempt, max_attempts (Req 11.8)
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

    def _emit_results(
        self, adapter: PipelineAdapter, fps: float, total_frames: int
    ) -> None:
        """Build final results from collected tracks and emit completion.

        Applies plate-based deduplication via :meth:`PipelineAdapter.finalize`
        (a no-op when plate reading is disabled, Req 14) before converting each
        track to a :class:`TrackResult` and emitting ``processing_finished``.
        Used for normal end-of-file completion, a stream "Stop" (Req 11.10),
        and stream loss after exhausted reconnection (Req 11.9) — in every case
        the results reflect the tracks collected up to that point.
        """
        all_tracks = adapter.tracker.get_all_tracks()
        finalized = adapter.finalize(all_tracks)
        results = [
            build_track_result(track, fps, total_frames)
            for track in finalized
        ]
        self.processing_finished.emit(results)

    def run(self) -> None:
        """Main processing loop — detect, track, OCR, emit signals per frame.

        Redirects stdout/stderr to the log panel, opens the selected video
        source (file or live stream), processes frames through
        :class:`PipelineAdapter`, optionally writes annotated frames to the
        output video, and emits per-frame and completion signals. Handles
        cancellation, frame-read failures, stream reconnection, and pipeline
        exceptions.

        File mode keeps determinate progress (current/total frames). Stream
        mode emits ``connecting`` before the first frame (Req 11.13), reports
        indeterminate progress (``total = -1``, Req 11.6), reconnects on read
        failure emitting ``reconnect_status`` (Req 11.8), and on
        :class:`StreamLostError` finishes with the tracks collected so far
        (Req 11.9). A ``cv2.VideoWriter`` is created only when an output path
        is set and No_Output_Mode is off (Req 15.4, 11.11).
        """
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        queue_io = QueueIO(self._record_log)
        sys.stdout = queue_io
        sys.stderr = queue_io

        is_stream = self.config.source_mode == "stream"
        source: VideoSource = (
            StreamVideoSource() if is_stream else FileVideoSource()
        )
        source_path = (
            self.config.stream_url if is_stream else self.config.video_path
        )
        writer: cv2.VideoWriter | None = None
        adapter: PipelineAdapter | None = None
        fps = 15.0
        total_frames = -1 if is_stream else 0
        frame_idx = 0

        try:
            # Stream: announce the connecting state before the first frame.
            if is_stream:
                self.connecting.emit(source_path)

            if not source.open(source_path):
                label = "stream" if is_stream else "video file"
                self.error.emit(f"Cannot open {label}: {source_path}", 0)
                return

            metadata: VideoMetadata = source.get_metadata()
            fps = metadata.fps if metadata.fps and metadata.fps > 0 else 15.0
            # Streams report frame_count == -1 (unknown) -> indeterminate.
            total_frames = metadata.frame_count

            adapter = PipelineAdapter(self.config, fps=fps)

            # Skip VideoWriter creation entirely in No_Output_Mode (Req 15.4)
            # or when no output path is set (e.g. a stream without recording,
            # Req 11.11).
            if not self.config.no_output and self.config.output_path:
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
                    if is_stream:
                        # Stream interrupted: reconnect up to MAX_RECONNECT
                        # times at 2s intervals; reconnect() raises
                        # StreamLostError once attempts are exhausted (Req
                        # 11.8/11.9).
                        attempt = source.reconnect()
                        self.reconnect_status.emit(
                            attempt, StreamVideoSource.MAX_RECONNECT
                        )
                        continue

                    # File: distinguish normal end-of-file from a mid-stream
                    # read failure.
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
                if is_stream:
                    # Successful read resets the reconnection counter.
                    source.reset_reconnect_attempts()

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
                if is_stream:
                    # Indeterminate progress: unknown total, no ETA. The
                    # ProcessingView shows elapsed/active/fps instead (Req
                    # 11.6/11.7).
                    self.progress.emit(processed, -1, elapsed, active_count, 0.0)
                else:
                    if processed > 0 and total_frames > 0:
                        remaining = max(0, total_frames - processed)
                        eta = (elapsed / processed) * remaining
                    else:
                        eta = 0.0
                    self.progress.emit(
                        processed, total_frames, elapsed, active_count, eta
                    )

                frame_idx += 1

            # Loop exited via cancellation or normal end-of-file.
            if self._cancel_event.is_set():
                if is_stream:
                    # Stream "Stop": switch to results with tracks collected so
                    # far (Req 11.10).
                    self._emit_results(adapter, fps, total_frames)
                # File "Cancel": discard incomplete output; the GUI returns to
                # the input panel (Req 3.6) — no completion signal.
                return

            # Normal end-of-file completion.
            self._emit_results(adapter, fps, total_frames)

        except StreamLostError as exc:
            # Stream could not be re-established after MAX_RECONNECT attempts:
            # finish with the tracks collected before the interruption (Req
            # 11.9).
            self._record_log(str(exc))
            if adapter is not None:
                self._emit_results(adapter, fps, total_frames)
        except Exception as exc:  # noqa: BLE001 - report any pipeline failure
            self.error.emit(f"{type(exc).__name__}: {exc}", frame_idx)
        finally:
            if writer is not None:
                writer.release()
            source.release()
            queue_io.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
