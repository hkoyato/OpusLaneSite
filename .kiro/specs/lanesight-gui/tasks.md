# Implementation Plan: Opus LaneSight GUI

## Overview

Build the PySide6 desktop GUI layer as a `gui/` package that wraps the existing vehicle detection pipeline. The implementation proceeds bottom-up: data models and utilities first, then settings persistence, brand theme, worker thread, individual views, and finally the main window wiring everything together. Tests validate correctness properties and widget behavior throughout.

## Tasks

- [x] 1. Set up gui/ package structure, data models, and utility functions
  - [x] 1.1 Create gui/ package directory with `__init__.py` and define data model dataclasses
    - Create `gui/__init__.py` with package docstring
    - Create `gui/models.py` with `ProcessingConfig`, `VideoMetadata`, `TrackResult`, and `AppSettings` dataclasses
    - Include type annotations and default values as specified in design
    - _Requirements: 10.3_

  - [x] 1.2 Implement utility functions for output path derivation, progress computation, confidence clamping, and file extension validation
    - Create `gui/utils.py`
    - Implement `derive_default_output_path(input_path: str) -> str` — returns `"output.mp4"` in same directory as input
    - Implement `compute_progress(current: int, total: int) -> float` — returns percentage [0, 100]
    - Implement `clamp_confidence(value: float) -> float` — clamps to [0.1, 1.0]
    - Implement `is_valid_video_extension(path: str) -> bool` — accepts .mp4, .avi, .mov, .mkv case-insensitive
    - Implement `build_track_result(vehicle, fps: float) -> TrackResult` — converts TrackedVehicle to TrackResult
    - Implement `compute_summary(results: list[TrackResult]) -> dict` — computes avg/max/min excluding None leave_time
    - Implement `sort_results_default(results: list[TrackResult]) -> list[TrackResult]` — ascending by enter_time
    - _Requirements: 2.7, 3.4, 4.1, 4.2, 4.3, 4.8, 8.5, 9.5, 9.6_

  - [x] 1.3 Write property tests for utility functions (Properties 1–5, 8–10)
    - Create `tests/test_gui_properties.py`
    - Configure Hypothesis with `@settings(max_examples=100)`
    - **Property 1: Default output path derivation** — for any valid Windows file path, output is "output.mp4" in same directory
    - **Property 2: Progress percentage invariant** — result always in [0, 100], equals (current/total)*100
    - **Property 3: TrackResult time computation** — enter_time = first_frame/fps, leave_time = last_frame/fps, wait_time >= 0
    - **Property 4: Summary statistics correctness** — only tracks with leave_time != None included in aggregates
    - **Property 5: Default sort order** — result is ascending by enter_time
    - **Property 8: Confidence threshold clamping** — result always in [0.1, 1.0], equals max(0.1, min(1.0, v))
    - **Property 9: Frame error counter accuracy** — count equals number of True (failure) values in sequence
    - **Property 10: File extension validation** — accepts only .mp4/.avi/.mov/.mkv case-insensitive
    - **Validates: Requirements 2.7, 3.4, 4.1, 4.2, 4.3, 4.8, 8.5, 8.3, 9.6**

- [x] 2. Implement settings persistence
  - [x] 2.1 Implement SettingsManager with JSON load/save at %LOCALAPPDATA%\OpusLaneSight\settings.json
    - Create `gui/settings.py`
    - Implement `SettingsManager` class with `_load()`, `_validate()`, `get()`, `update()`, `save()` methods
    - Handle missing file (create with defaults), corrupt JSON (overwrite with defaults), out-of-range values (clamp to valid)
    - Handle non-writable directory gracefully (in-memory operation + warning flag)
    - Create directory if not exists
    - Debounce or immediate save within 2 seconds of modification
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 2.2 Write property tests for settings round-trip and invalid settings recovery (Properties 6–7)
    - **Property 6: Settings round-trip persistence** — serialize then deserialize produces identical AppSettings
    - **Property 7: Invalid settings produce valid defaults** — any invalid JSON string or out-of-range dict yields valid AppSettings
    - **Validates: Requirements 5.2, 5.3**

  - [x] 2.3 Write unit tests for SettingsManager
    - Test directory creation when missing
    - Test default values applied on first launch
    - Test corrupt file recovery
    - Test value clamping for out-of-range confidence and OCR interval
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 3. Implement brand theme
  - [x] 3.1 Create BrandTheme with color constants, gradient, font setup, and QSS stylesheet generator
    - Create `gui/theme.py`
    - Define all color constants (TEAL_DARK, TEAL, GREEN, BLUE, ORANGE, CHARCOAL, GRAY, BG, WHITE, CARD_BORDER)
    - Define HEADER_GRADIENT as qlineargradient
    - Implement `get_stylesheet() -> str` producing full QSS with card styles, button styles, header gradient, font sizes
    - Implement `apply(app: QApplication)` — sets Roboto font family with fallback to Arial/Segoe UI, applies stylesheet
    - Implement card styling helper for 14px border-radius, white background, shadow, border
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 3.2 Add Opus logo PNG and application icon to gui/resources/
    - Create `gui/resources/` directory
    - Add Opus logo PNG (copy from branding/ directory, sized for 36px min height in header)
    - Create or source an application `.ico` file consistent with Opus brand
    - Create `gui/resources/__init__.py` or resource path helper
    - _Requirements: 7.4, 9.4_

  - [x] 3.3 Write unit tests for BrandTheme
    - Verify stylesheet contains expected hex color values
    - Verify gradient string matches spec
    - Verify font family includes Roboto
    - _Requirements: 7.1, 7.2, 7.6_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement WorkerThread and PipelineAdapter
  - [x] 5.1 Implement VideoSource protocol and FileVideoSource class
    - Create `gui/worker.py`
    - Define `VideoSource` Protocol with `open()`, `read()`, `get_metadata()`, `release()` methods
    - Implement `FileVideoSource` wrapping `cv2.VideoCapture` for local files
    - `get_metadata()` returns `VideoMetadata` dataclass
    - _Requirements: 10.2, 6.1_

  - [x] 5.2 Implement PipelineAdapter class
    - Implement `PipelineAdapter.__init__(config: ProcessingConfig)` — instantiates VehicleDetector, VehicleTracker, AppearanceExtractor, and optionally PlateOCR/PlateTextAggregator without modifying pipeline source
    - Implement `process_frame(frame, frame_idx) -> tuple[np.ndarray, list, int]` — runs detect → track → OCR → annotate pipeline for one frame
    - Pass parameters using same names/types as main.py `process_video` function
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 5.3 Implement WorkerThread (QThread) with signals and cancellation
    - Implement `WorkerThread(QThread)` with signals: `frame_ready`, `progress`, `frame_error`, `finished`, `error`, `log_output`
    - Implement `run()` method — opens VideoSource, loops frames, calls PipelineAdapter, emits signals, handles cancellation via `threading.Event`
    - Implement stdout/stderr capture using `QueueIO` class redirecting to `log_output` signal (max 10,000 lines via deque)
    - Implement `request_cancel()` — sets cancellation Event, thread checks per-frame and stops within 1 second
    - Handle frame-read failures: skip frame, increment error counter, emit `frame_error` signal
    - Abort if consecutive frame failures exceed 100
    - Convert TrackedVehicle list to TrackResult list on completion using `build_track_result`
    - Write annotated frames to output video via cv2.VideoWriter
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.3, 6.4, 6.5, 6.6, 8.3, 8.6, 10.4_

  - [x] 5.4 Write unit tests for WorkerThread signal emission
    - Mock VehicleDetector and tracker to return canned detections
    - Verify frame_ready signal emitted with QImage, frame_idx, track_count
    - Verify progress signal emitted with correct values
    - Verify cancellation stops thread within expected time
    - Verify error signal emitted on pipeline exception
    - _Requirements: 3.1, 3.6, 3.7, 6.5, 6.6_

- [x] 6. Implement InputPanel view
  - [x] 6.1 Implement InputPanel widget with file selection, metadata display, and parameter controls
    - Create `gui/input_panel.py`
    - Implement `InputPanel(QWidget)` with `start_requested = Signal(ProcessingConfig)`
    - Add file selection button opening native Windows file dialog filtered to MP4, AVI, MOV, MKV
    - Implement `validate_video(path)` — opens with cv2.VideoCapture, reads one frame, extracts VideoMetadata
    - Display file name, path, resolution, frame count, duration, FPS in a summary card on successful selection
    - Show inline error for invalid/unreadable files
    - Add confidence slider (range 0.1–1.0, step 0.05, default 0.5, numeric label to 2 decimal places)
    - Add OCR toggle switch (default disabled) with tooltip
    - Show OCR language dropdown and OCR interval input (1–100, default 10) when OCR enabled
    - Add output path selector (defaults to "output.mp4" in input video directory, no default until video selected)
    - Add "Start processing" button disabled until valid video selected
    - Implement `set_video_from_drop(path)` for drag-and-drop support
    - Implement `build_config() -> ProcessingConfig` to collect all parameters
    - Load initial values from SettingsManager
    - Save setting changes back to SettingsManager within 2 seconds
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 5.1, 5.2, 8.5_

  - [x] 6.2 Write unit tests for InputPanel widget state
    - Test start button disabled until valid video selected
    - Test OCR controls hidden when toggle off, visible when on
    - Test confidence slider range and step
    - Test output path defaults to input directory after video selection
    - Use QT_QPA_PLATFORM=offscreen for headless testing
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 7. Implement ProcessingView
  - [x] 7.1 Implement ProcessingView widget with live frame display, progress bar, stats, and cancel
    - Create `gui/processing_view.py`
    - Implement `ProcessingView(QWidget)` with `cancel_requested = Signal()`
    - Add QLabel for live annotated frame display (convert QImage to QPixmap, scale to fit)
    - Add progress bar (percentage based on current/total frames)
    - Add statistics panel: current frame, total frames, elapsed time, active vehicle count, estimated time remaining — updated at least once per second
    - Add skipped frames error counter display
    - Add "Cancel" button emitting `cancel_requested` signal
    - Implement slots: `on_frame_ready(QImage, int, int)`, `on_progress(int, int, float, int, float)`, `on_frame_error(int)`
    - Target at least 5 FPS preview update rate
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 8.3_

  - [x] 7.2 Write unit tests for ProcessingView
    - Test progress bar value updates correctly
    - Test stats labels format elapsed time and ETA
    - Test error counter increments on frame_error slot
    - _Requirements: 3.4, 3.5, 8.3_

- [x] 8. Implement ResultsView
  - [x] 8.1 Implement ResultsView widget with vehicle table, summary cards, and new session button
    - Create `gui/results_view.py`
    - Implement `ResultsView(QWidget)` with `new_session_requested = Signal()`
    - Implement `display_results(results, fps, ocr_enabled, output_path, skipped_frames, total_frames)`
    - Build sortable QTableWidget with columns: Vehicle ID, Plate Text, Confidence, Enter Time, Leave Time, Wait Time
    - Hide Plate Text and Confidence columns when OCR disabled
    - Display "—" for Leave Time and Wait Time when vehicle has no leave_time
    - Default sort: ascending by Enter Time; clickable headers toggle asc/desc
    - Display summary metric cards: total vehicles, average wait, max wait, min wait (exclude vehicles without leave_time)
    - Display skipped frames warning if > 0
    - Display output file path with "Open folder" button (calls `os.startfile` on containing directory)
    - Display empty-state message when zero vehicles detected
    - Add "New session" button emitting `new_session_requested`
    - Format times to 1 decimal place, confidence to 2 decimal places
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 8.4_

  - [x] 8.2 Write unit tests for ResultsView
    - Test column count and visibility with OCR on/off
    - Test empty state message shown when no results
    - Test sort order changes on header click
    - Test summary stats exclude vehicles without leave_time
    - _Requirements: 4.1, 4.2, 4.3, 4.6, 4.7, 4.8_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement MainWindow and application entry point
  - [x] 10.1 Implement MainWindow with sidebar navigation, view stack, and event handling
    - Create `gui/main_window.py`
    - Implement `MainWindow(QMainWindow)` with sidebar nav (Input, Processing, Results + 3 placeholder slots for future views)
    - Use QStackedWidget for view switching
    - Set minimum window size 1024×700, support resizing
    - Apply BrandTheme stylesheet on init
    - Build branded header: gradient background, Opus logo (36px min height), "Opus LaneSight" title, subtitle
    - Add privacy trust note footer visible across all views
    - Implement `switch_view(view_name)` updating window title: "Opus LaneSight - Ready/Processing [filename]/Results"
    - Implement `start_processing(config)` — validate model file exists, validate output path writable, create WorkerThread, connect signals, switch to ProcessingView
    - Implement `on_worker_finished(results)` — switch to ResultsView
    - Implement `on_worker_error(error_msg, frame_idx)` — show error dialog, return to InputPanel
    - Implement `closeEvent` — confirm exit during processing with "Cancel and exit" / "Continue processing" dialog
    - Implement drag-and-drop: `dragEnterEvent` accepts valid video extensions, `dropEvent` validates and passes to InputPanel
    - Reject invalid drop extensions with error message
    - Restore window geometry from SettingsManager on launch, save on resize/move
    - Set custom window icon from gui/resources/
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.4, 7.6, 8.1, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.5_

  - [x] 10.2 Create application entry point (`gui/__main__.py`)
    - Create `gui/__main__.py`
    - Initialize QApplication with `sys.argv`
    - Apply BrandTheme
    - Set QT_QPA_PLATFORM if needed
    - Handle startup ImportError for PySide6 — show error dialog with dependency name, exit gracefully
    - Instantiate MainWindow, show, run event loop
    - Handle unrecoverable startup errors with error dialog
    - _Requirements: 1.1, 1.4, 1.6_

  - [x] 10.3 Write unit tests for MainWindow
    - Test view switching updates window title correctly
    - Test drag-and-drop accepts valid extensions and rejects invalid
    - Test close event shows confirmation during processing
    - Test sidebar holds at least 6 nav entries without overflow
    - _Requirements: 9.3, 9.5, 9.6, 10.1_

- [x] 11. Integration testing and final wiring
  - [x] 11.1 Write integration tests for full processing flow
    - Mock VehicleDetector to return canned detections (no GPU/model needed)
    - Verify start → WorkerThread signals → ProcessingView updates → finished → ResultsView populated
    - Verify cancellation flow: start → cancel → thread stops → return to InputPanel
    - Verify error flow: inject exception → error signal → error dialog → InputPanel
    - Verify settings persistence: modify settings → relaunch SettingsManager → values match
    - Use QT_QPA_PLATFORM=offscreen
    - _Requirements: 3.1, 3.6, 3.7, 6.5, 6.6, 5.2_

  - [x] 11.2 Wire stdout/stderr log capture to a collapsible log panel in MainWindow
    - Add collapsible log panel (QTextEdit or QPlainTextEdit) to MainWindow
    - Connect WorkerThread `log_output` signal to append text to log panel
    - Limit display to most recent 10,000 lines using collections.deque
    - Ensure pipeline console output does not appear in background console window
    - _Requirements: 6.4_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Tasks (Extension — Requirements 11–15)

- [x] 13. Extend data models for stream input, detector backend, interval, and no-output
  - [x] 13.1 Add new fields to ProcessingConfig and AppSettings dataclasses
    - Edit `gui/models.py`
    - Extend `ProcessingConfig` with `source_mode: str` ("file" | "stream"), `stream_url: str`, `detector_backend: str` ("yolo" | "rekognition"), `aws_region: str`, `detect_interval: int`, `no_output: bool`, and change `output_path` to `output_path: str | None`
    - Extend `AppSettings` with `detector_backend: str = "yolo"`, `aws_region: str = "us-east-1"`, `detect_interval: int = 1`, `no_output: bool = False`, `source_mode: str = "file"`
    - Keep type annotations and defaults exactly as specified in the design Data Models section
    - _Requirements: 11.1, 11.2, 11.4, 12.1, 12.2, 12.4, 13.1, 13.2, 15.1, 15.4_

- [x] 14. Extend utility/pure-logic functions for the new correctness properties
  - [x] 14.1 Implement stream URL, AWS region, detect-interval, and plate-dedup utility functions
    - Edit `gui/utils.py`
    - Implement `is_valid_stream_url(url: str) -> bool` — trims whitespace; accepts iff non-empty, length <= 2048, and begins (case-insensitive) with `rtsp://`, `rtmp://`, `http://`, or `https://`
    - Implement `is_valid_aws_region(region: str) -> bool` — trims whitespace; accepts iff non-empty and length in [1, 64]
    - Implement `clamp_detect_interval(value: float) -> int` — returns `max(1, min(60, round(value)))`
    - Implement `parse_detect_interval(text: str, last_valid: int) -> int` — returns clamped integer when `text` denotes an integer; otherwise returns `last_valid` unchanged
    - Implement `deduplicate_by_plate(tracks: list, enabled: bool) -> list` — when `enabled` is False returns tracks unchanged; when True groups tracks via `plate_utils` (`plates_are_similar`, `normalize_plate`, `pick_best_plate`) replicating `main._deduplicate_by_plate` semantics (merged row uses min first_frame, max last_frame, summed hit_count, best plate; tracks with no plate text or < 3 chars stay separate); idempotent
    - Import the dedup helpers from the unmodified `plate_utils` module (do not re-implement fuzzy matching)
    - _Requirements: 11.2, 11.5, 11.12, 12.5, 13.4, 13.5, 13.6, 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 14.2 Write property tests for the new utility functions (Properties 11, 14, 15, 16, 17, 18)
    - Append to `tests/test_gui_properties.py` using `@settings(max_examples=100)`
    - **Property 11: Stream URL scheme validation** — `is_valid_stream_url` accepts iff trimmed, non-empty, <= 2048 chars, supported scheme prefix
    - **Property 14: AWS region validation** — `is_valid_aws_region` accepts iff trimmed non-empty and length in [1, 64]
    - **Property 15: Detection interval clamping** — `clamp_detect_interval(v)` equals `max(1, min(60, round(v)))`, always in [1, 60]
    - **Property 16: Detection interval non-integer rejection** — `parse_detect_interval` accepts iff entry denotes an integer; otherwise preserves last valid value
    - **Property 17: Plate deduplication merge invariants** — grouping by equal/confusable-normalized plate; merged frame span, summed hits, best plate; short/absent plate tracks stay separate
    - **Property 18: Deduplication identity-when-disabled and idempotence** — identity when disabled; `dedup(dedup(t)) == dedup(t)` when enabled
    - **Validates: Requirements 11.2, 11.5, 11.12, 12.5, 13.4, 13.5, 13.6, 14.1, 14.2, 14.3, 14.4, 14.5**

- [x] 15. Extend SettingsManager validation for the new persisted fields
  - [x] 15.1 Extend SettingsManager `_validate()` with fallbacks for the 5 new fields
    - Edit `gui/settings.py`
    - Validate `detector_backend` against `{"yolo", "rekognition"}` (else `"yolo"`)
    - Validate `aws_region` as a 1–64 char non-empty string (else `"us-east-1"`)
    - Clamp `detect_interval` to [1, 60]; non-integers fall back to 1
    - Validate `no_output` as boolean (else `false`)
    - Validate `source_mode` against `{"file", "stream"}` (else `"file"`)
    - Ensure all new fields are serialized in `save()` and round-trip through `get()`/`update()`
    - _Requirements: 5.3, 12.2, 15.1, 15.6_

  - [x] 15.2 Write property test (Property 20) and unit tests for new-field fallbacks
    - Append to `tests/test_gui_properties.py`
    - **Property 20: Extended settings round-trip persistence** — valid AppSettings (incl. new fields) serialize→deserialize identically; invalid/out-of-range new-field values fall back to documented defaults
    - **Validates: Requirements 5.3, 12.2, 15.1, 15.6**
    - Add unit tests for each new-field range/enum fallback (invalid `detector_backend`, empty/over-long `aws_region`, out-of-range and non-integer `detect_interval`, non-boolean `no_output`, invalid `source_mode`)
    - _Requirements: 5.3, 12.2, 15.1, 15.6_

- [x] 16. Implement StreamVideoSource for live stream input
  - [x] 16.1 Implement StreamVideoSource and StreamLostError in gui/worker.py
    - Edit `gui/worker.py`
    - Implement `StreamVideoSource` satisfying the `VideoSource` protocol with `is_stream()` returning True
    - On `open()`, set `cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)`; default FPS to 25.0 when the stream reports none; `get_metadata()` returns `total_frames = -1`
    - Define `MAX_RECONNECT = 5` and `RECONNECT_INTERVAL_SECONDS = 2`
    - Implement `reconnect() -> int` — releases and re-opens the capture, returns the current attempt number (1..5); raise `StreamLostError` after `MAX_RECONNECT` failures
    - Mirror the backend stream handling in `main.py` without importing or modifying it
    - _Requirements: 11.2, 11.6, 11.8, 11.9_

  - [x] 16.2 Write unit/integration tests for stream reconnection counting (Property 13)
    - Create/extend `tests/test_worker_stream.py` with a fake `cv2.VideoCapture` (mocked) that fails reads on demand
    - **Property 13: Stream reconnection attempt counting** — for `k` consecutive failures the reported attempt equals `min(k, 5)`, and `StreamLostError`/exhaustion is signaled iff `k > 5`
    - Verify `CAP_PROP_BUFFERSIZE` set, default FPS 25.0, and `total_frames == -1`
    - _Requirements: 11.8, 11.9_

- [x] 17. Extend PipelineAdapter for backend selection, interval, and dedup finalize
  - [x] 17.1 Extend PipelineAdapter to select detector backend and honor detect_interval
    - Edit `gui/worker.py` `PipelineAdapter`
    - In `__init__`, construct `RekognitionDetector(region_name=config.aws_region, confidence=config.confidence, use_rekognition_text=config.ocr_enabled)` when `detector_backend == "rekognition"`, else `VehicleDetector(...)` as today; store `detect_interval`
    - When Rekognition is selected, create a `PlateTextAggregator` so Rekognition-provided `plate_text` can be aggregated only when plate reading is enabled
    - In `process_frame`, run `detector.detect()` only when `frame_idx % detect_interval == 0`; on skipped frames call `tracker.update([], frame_idx, None)` so the Kalman filter predicts
    - Feed Rekognition `plate_text` into the aggregator (mirroring `main.py`)
    - Implement `finalize(tracks)` applying `deduplicate_by_plate` (via `plate_utils`) only when plate reading is enabled; otherwise return tracks unchanged
    - Do not import or modify `process_video`, `detector_rekognition.py`, or `plate_utils.py`
    - _Requirements: 12.4, 12.8, 13.2, 14.1, 14.2, 14.3, 14.4_

- [x] 18. Extend WorkerThread for stream/file source, new signals, and no-output
  - [x] 18.1 Extend WorkerThread run loop, signals, and VideoWriter gating
    - Edit `gui/worker.py` `WorkerThread`
    - Add signals `connecting = Signal(str)` and `reconnect_status = Signal(int, int)`
    - In `run()`, select `FileVideoSource` or `StreamVideoSource` based on `config.source_mode`
    - Stream mode: emit `connecting(stream_url)` before the first frame; emit indeterminate progress (`total = -1`); on read failure call `StreamVideoSource.reconnect()` and emit `reconnect_status(attempt, MAX_RECONNECT)`; on `StreamLostError` finish with collected tracks
    - File mode: keep determinate progress as today
    - Skip `cv2.VideoWriter` creation entirely when `config.no_output` is True or `config.output_path is None`
    - Honor Stop/Cancel via the existing `threading.Event`, stopping within 3s and finishing with tracks collected so far
    - Call `PipelineAdapter.finalize()` before emitting `finished`
    - _Requirements: 11.4, 11.6, 11.8, 11.9, 11.10, 11.11, 11.13, 15.4_

  - [x] 18.2 Write unit tests for WorkerThread stream/no-output behavior
    - Extend `tests/test_worker_stream.py`
    - Verify `connecting` emitted before first stream frame; `reconnect_status` emitted on interruption; finish-with-collected-tracks on exhaustion
    - Verify indeterminate progress (`total == -1`) in stream mode
    - Verify VideoWriter is skipped when `no_output` is True or `output_path is None`
    - Verify Stop stops the thread within the expected time
    - _Requirements: 11.6, 11.8, 11.9, 11.10, 11.13, 15.4_

- [x] 19. Extend InputPanel with source mode, backend, interval, and no-output controls
  - [x] 19.1 Add the new InputPanel controls, validation, and config mapping
    - Edit `gui/input_panel.py`
    - Add `Input_Source_Mode` selector ("Video file" | "Live stream", default "Video file") and a conditional stream URL field (max 2048 chars), shown only in stream mode; disable file controls in stream mode (`on_source_mode_changed`)
    - Add `Detector_Backend` selector ("Local YOLOv8" | "AWS Rekognition", default "Local YOLOv8") and a conditional AWS region field (1–64 chars, default "us-east-1"), shown only for Rekognition (`on_detector_backend_changed`)
    - Add `Detection_Interval` spinbox (1–60, step 1, default 1); show the 5–10 recommendation when Rekognition is selected
    - Add `No_Output_Mode` toggle that disables the output path selector when enabled (`on_no_output_toggled`); persist via SettingsManager
    - Show the Requirement 1.5 privacy note when Rekognition + plate reading is enabled
    - Implement `validate_before_start()` returning inline errors for: empty/whitespace stream URL (stream mode), unsupported stream URL scheme, empty/whitespace AWS region (Rekognition); do not start when invalid
    - Extend `build_config()` to map source_mode/stream_url/video_path, detector_backend ("yolo"|"rekognition"), aws_region, detect_interval, and `output_path = None` when no-output is enabled
    - Load/restore the new fields from SettingsManager and persist changes within 2 seconds
    - _Requirements: 11.1, 11.2, 11.3, 11.5, 11.12, 12.1, 12.2, 12.3, 12.5, 12.9, 13.1, 13.3, 15.2, 15.3, 15.6_

  - [x] 19.2 Write unit and property tests for InputPanel (Properties 12, 19)
    - Add widget unit tests (headless, `QT_QPA_PLATFORM=offscreen`): source-mode default + stream URL field visibility, file controls disabled in stream mode, detector-backend default + AWS region visibility, detect-interval bounds/default, Rekognition 5–10 recommendation visible, no-output toggle disables output path selector, privacy note under Rekognition + plate reading, `validate_before_start` error cases
    - Append to `tests/test_gui_properties.py`:
    - **Property 12: ProcessingConfig source/parameter mapping** — stream/file mode URL/path mapping, backend maps to "yolo"/"rekognition", aws_region carried through, detect_interval integer in [1, 60]
    - **Property 19: No-output mode config mapping** — `output_path is None` and `no_output is True` when enabled; non-None path when disabled
    - **Validates: Requirements 11.4, 12.4, 13.2, 15.4**

- [x] 20. Extend ProcessingView for indeterminate progress and stream status
  - [x] 20.1 Add indeterminate progress, connecting/reconnect slots, and Stop label
    - Edit `gui/processing_view.py`
    - Switch the progress bar to indeterminate (range 0,0) when `on_progress` receives `total == -1`; show elapsed time, active vehicle count, and effective FPS instead of a percentage
    - Implement `on_connecting(stream_url)` slot showing a connecting status message identifying the target URL
    - Implement `on_reconnect_status(attempt, max_attempts)` slot showing "Reconnecting (attempt/max)..."
    - Label the cancel control "Stop" in stream mode
    - _Requirements: 11.6, 11.7, 11.8, 11.10, 11.13_

  - [x] 20.2 Write unit tests for ProcessingView stream behavior
    - Extend `tests/` ProcessingView tests
    - Test indeterminate mode when `total == -1`, connecting status text shows URL, reconnection status text format, Stop button label in stream mode
    - _Requirements: 11.6, 11.8, 11.13_

- [x] 21. Extend ResultsView for deduplicated rows and no-output state
  - [x] 21.1 Display deduplicated rows and handle None output path
    - Edit `gui/results_view.py`
    - When plate reading is enabled, treat incoming `results` as the deduplicated rows and show Plate Text / Confidence columns; when disabled, show every track as a separate row with those columns hidden
    - Compute summary statistics from the displayed (deduplicated) row set
    - When `output_path is None`, hide the output path label and open-folder button and display "No output video written"
    - _Requirements: 14.1, 14.4, 14.5, 15.5_

  - [x] 21.2 Write unit tests for ResultsView extensions
    - Test deduplicated rows shown when plate reading enabled vs separate rows when disabled
    - Test output path label and open-folder button omitted with "No output video written" when `output_path is None`
    - _Requirements: 14.1, 14.4, 15.5_

- [x] 22. Extend MainWindow wiring, AWS error handling, and integration tests
  - [x] 22.1 Extend MainWindow start_processing and stream/AWS handling
    - Edit `gui/main_window.py`
    - Connect the new `connecting` and `reconnect_status` signals to the ProcessingView slots
    - In `start_processing`, classify AWS Rekognition failures: credentials errors (e.g., `NoCredentialsError`, `UnrecognizedClient`, `InvalidSignature`) vs region/service/network errors (`ClientError`, `EndpointConnectionError`, `BotoCoreError`); show the matching message and return to InputPanel retaining selections
    - On stream finish/Stop/loss, switch to ResultsView with the tracks collected so far
    - _Requirements: 11.9, 11.10, 12.6, 12.7_

  - [x] 22.2 Write integration tests with boto3 mocked, stream reconnection, and Stop
    - Create/extend `tests/test_integration_extension.py` (headless, `QT_QPA_PLATFORM=offscreen`)
    - Patch `boto3.client` (no live AWS) so `RekognitionDetector.detect()` returns canned detections; verify the adapter selects Rekognition for `detector_backend="rekognition"` and threads `plate_text` into the aggregator
    - Inject `NoCredentialsError` and a service `ClientError`; verify credentials vs service/region classification and return to InputPanel
    - Stream reconnection integration test: fake `StreamVideoSource` yielding N frames then failing; verify indeterminate progress, `reconnect_status` emissions, and finish-with-collected-tracks on exhaustion
    - Stream Stop control test: verify stop within 3s and switch to ResultsView
    - _Requirements: 11.9, 11.10, 12.5, 12.6, 12.7_

- [x] 23. Add boto3 dependency
  - [x] 23.1 Add boto3 to requirements.txt
    - Edit `requirements.txt`
    - Add a pinned `boto3` entry (Apache-2.0) with a comment noting it is required for the AWS Rekognition detector backend
    - _Requirements: 12.4_

- [x] 24. Final checkpoint - Ensure all extension tests pass
  - Ensure all tests pass (all run headless with `QT_QPA_PLATFORM=offscreen`; AWS is always mocked), ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests run headless with `QT_QPA_PLATFORM=offscreen` — no display server required
- The existing pipeline modules (detector.py, tracker.py, ocr.py, appearance.py, plate_detector.py, detector_rekognition.py, plate_utils.py, main.py) must NOT be modified
- PySide6 is used (LGPL license) — must be added to requirements.txt
- boto3 (Apache-2.0) is required only for the AWS Rekognition backend (Tasks 13–24); all Rekognition tests mock `boto3` and never call live AWS

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.2"] },
    { "id": 1, "tasks": ["1.2", "3.1"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.3"] },
    { "id": 3, "tasks": ["2.2", "2.3", "5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["5.3"] },
    { "id": 6, "tasks": ["5.4", "6.1", "7.1", "8.1"] },
    { "id": 7, "tasks": ["6.2", "7.2", "8.2"] },
    { "id": 8, "tasks": ["10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "11.2"] },
    { "id": 10, "tasks": ["11.1"] },
    { "id": 11, "tasks": ["13.1"] },
    { "id": 12, "tasks": ["14.1", "16.1", "23.1"] },
    { "id": 13, "tasks": ["14.2", "15.1", "16.2", "17.1"] },
    { "id": 14, "tasks": ["15.2", "18.1"] },
    { "id": 15, "tasks": ["18.2", "19.1", "20.1", "21.1"] },
    { "id": 16, "tasks": ["19.2", "20.2", "21.2"] },
    { "id": 17, "tasks": ["22.1"] },
    { "id": 18, "tasks": ["22.2"] }
  ]
}
```
