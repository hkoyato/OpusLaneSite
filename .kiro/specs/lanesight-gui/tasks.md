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

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests run headless with `QT_QPA_PLATFORM=offscreen` — no display server required
- The existing pipeline modules (detector.py, tracker.py, ocr.py, appearance.py, plate_detector.py) must NOT be modified
- PySide6 is used (LGPL license) — must be added to requirements.txt

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
    { "id": 10, "tasks": ["11.1"] }
  ]
}
```
