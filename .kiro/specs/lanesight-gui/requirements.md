# Requirements Document

## Introduction

The Opus LaneSight GUI is a self-contained, lightweight Windows desktop application that wraps the existing Python-based vehicle detection and tracking pipeline in a graphical interface. The GUI provides station operators and demo presenters with a visual workflow for selecting input video, configuring detection parameters, monitoring processing progress with live annotated preview, and viewing per-vehicle wait-time results. The application is built using a Python GUI framework (PySide6/PyQt6) to share the same runtime as the backend pipeline modules. It adheres to the Opus LaneSight brand guidelines and is designed to accommodate future features such as RTSP/RTMP input, lane/zone polygon definition, and operational dashboards without requiring a rewrite.

## Glossary

- **GUI_Application**: The standalone PySide6/PyQt6 desktop window application that orchestrates the existing detection pipeline through a graphical interface.
- **Pipeline**: The existing Python modules (detector.py, tracker.py, ocr.py, appearance.py, plate_detector.py) that perform vehicle detection, tracking, and optional OCR.
- **Processing_Session**: A single run of the Pipeline against a selected video file, from start to completion or cancellation.
- **Video_Input_Panel**: The GUI view where the user selects and configures input video and processing parameters.
- **Processing_View**: The GUI view displayed during active video processing, showing live annotated frames and progress.
- **Results_View**: The GUI view displayed after processing completes, showing per-vehicle wait-time data and summary statistics.
- **Settings_Panel**: The GUI section or dialog where the user configures detection confidence, OCR options, output path, and display preferences.
- **Worker_Thread**: A background thread that executes the Pipeline processing to keep the GUI responsive.
- **Confidence_Threshold**: A floating-point value between 0 and 1 that controls the minimum detection score for vehicle identification.
- **OCR_Toggle**: A user-facing control that enables or disables license plate OCR processing during a session.
- **Brand_Theme**: The visual appearance system implementing Opus color palette, Roboto typography, card-based layout, and spacing rules per the UI guidelines.
- **Stream_Source**: A live video input identified by an RTSP, RTMP, or HTTP stream URL, processed indefinitely until the user stops it, as an alternative to a local video file.
- **Input_Source_Mode**: The mutually exclusive selection between file input (a local video file) and stream input (a Stream_Source URL) for a Processing_Session.
- **Detector_Backend**: The selectable vehicle detection engine, either the local YOLOv8 detector ("yolo") or the AWS Rekognition cloud detector ("rekognition").
- **AWS_Region**: The AWS region string (e.g., "us-east-1") used for AWS Rekognition API calls when the Rekognition Detector_Backend is selected.
- **Detection_Interval**: A positive integer N controlling that vehicle detection runs every N frames, with Kalman prediction filling the gaps between detection frames, to reduce GPU load (YOLO) or API calls and cost (Rekognition).
- **Plate_Deduplication**: The post-processing step that merges tracks with the same or fuzzy-similar plate text into a single result, combining frame ranges and hit counts and selecting the best plate text, applied only when plate text reading is enabled.
- **No_Output_Mode**: A configuration option that disables writing the annotated output video for faster processing.
- **Plate_Text_Reading**: Any capability that reads license plate text, including EasyOCR (local OCR) and AWS Rekognition DetectText; it is opt-in and disabled by default to preserve the privacy-preserving positioning.

## Requirements

### Requirement 1: Application launch and main window

**User Story:** As a station operator, I want to launch the LaneSight GUI as a standalone Windows application, so that I can process video files without using the command line.

#### Acceptance Criteria

1. WHEN the user launches the GUI_Application executable, THE GUI_Application SHALL display a main window within 10 seconds, showing the Opus logo, product name "Opus LaneSight", and subtitle "AI-powered station wait-time intelligence" in the header area.
2. THE GUI_Application SHALL apply the Brand_Theme using the Opus color palette with teal-dark (#004851) header background, Roboto font family, and light background (#F4F7F7) for the content area.
3. THE GUI_Application SHALL set a minimum window size of 1024x700 pixels and support resizing to larger dimensions.
4. WHEN the GUI_Application launches, THE GUI_Application SHALL display the Video_Input_Panel as the default view.
5. WHILE the GUI_Application is running, THE GUI_Application SHALL display a privacy trust note in the window footer across all views, stating that LaneSight uses temporary anonymous vehicle session IDs and does not read or store license plates or driver identities.
6. IF the GUI_Application fails to initialize due to missing critical dependencies or an unrecoverable startup error, THEN THE GUI_Application SHALL display an error dialog describing the failure reason and exit gracefully without crashing silently.

### Requirement 2: Video file selection and input configuration

**User Story:** As a station operator, I want to select an MP4 video file and configure processing parameters through the GUI, so that I can start analysis without remembering CLI flags.

#### Acceptance Criteria

1. WHEN the user clicks the file selection button on the Video_Input_Panel, THE GUI_Application SHALL open a native Windows file dialog filtered to video files (MP4, AVI, MOV, MKV).
2. WHEN the user selects a video file that OpenCV can successfully open and read at least one frame from, THE Video_Input_Panel SHALL display the file name, file path, and video metadata (resolution, frame count, duration, FPS) in a summary card within 2 seconds of selection.
3. IF the user selects a file that cannot be opened by OpenCV or from which no frames can be read, THEN THE GUI_Application SHALL display an inline error message on the Video_Input_Panel indicating the file format is unsupported or the file is corrupt, and SHALL keep the file selection button enabled for the user to choose a different file.
4. THE Video_Input_Panel SHALL provide a Confidence_Threshold slider with a range of 0.1 to 1.0, a step increment of 0.05, a default value of 0.5, and a numeric label displaying the current value to two decimal places.
5. THE Video_Input_Panel SHALL provide an OCR_Toggle switch defaulting to disabled, with a tooltip explaining that OCR reads plate text for development and testing purposes only.
6. WHEN OCR is enabled via the OCR_Toggle, THE Video_Input_Panel SHALL display additional OCR settings: a language selection dropdown (default "en") and an OCR frame interval numeric input with a range of 1 to 100 frames and a default value of 10.
7. THE Video_Input_Panel SHALL provide an output file path selector that defaults to "output.mp4" in the same directory as the selected input video, and displays no default path until an input video has been selected.
8. THE Video_Input_Panel SHALL provide a "Start processing" button that is disabled until the user has selected a file that OpenCV can successfully open, and enabled thereafter.

### Requirement 3: Processing execution and live preview

**User Story:** As a station operator, I want to see live annotated video frames and progress during processing, so that I can confirm the system is detecting vehicles correctly.

#### Acceptance Criteria

1. WHEN the user clicks "Start processing", THE GUI_Application SHALL switch to the Processing_View and begin Pipeline execution on a Worker_Thread.
2. WHILE the Pipeline is executing on the Worker_Thread, THE GUI_Application SHALL remain responsive to user interaction (window resize, minimize, and cancel actions) such that any user-initiated UI action receives a visible response within 500 milliseconds.
3. WHILE processing is active, THE Processing_View SHALL display the current annotated frame with vehicle bounding boxes, anonymous vehicle IDs, and plate bounding boxes (when plate detection is active) at a rate of at least 5 frames per second in the preview.
4. WHILE processing is active, THE Processing_View SHALL display a progress bar showing percentage complete based on current frame divided by total frames.
5. WHILE processing is active, THE Processing_View SHALL display statistics updated at least once per second: current frame number, total frames, elapsed time, active vehicle count, and estimated time remaining.
6. WHEN the user clicks the "Cancel" button during processing, THE GUI_Application SHALL stop the Worker_Thread within 3 seconds, release video resources, discard any incomplete output file, and return to the Video_Input_Panel with a cancellation confirmation message.
7. IF the Pipeline raises an unhandled exception, fails to open the video source, or loses access to the YOLO model during execution, THEN THE GUI_Application SHALL stop processing, display an error message indicating the failure type and the frame number at which it occurred, and return to the Video_Input_Panel.

### Requirement 4: Results display

**User Story:** As a station operator, I want to view per-vehicle wait-time results and summary statistics after processing completes, so that I can understand station throughput without parsing console output.

#### Acceptance Criteria

1. WHEN Pipeline processing completes with one or more tracked vehicles, THE GUI_Application SHALL switch to the Results_View displaying a table of tracked vehicles with columns: Vehicle ID, Plate Text (if OCR was enabled), Confidence (displayed to 2 decimal places), Enter Time (seconds, 1 decimal place), Leave Time (seconds, 1 decimal place), and Wait Time (seconds, 1 decimal place).
2. THE Results_View SHALL display summary statistics in metric cards: total vehicles tracked, average wait time (seconds, 1 decimal place), maximum wait time (seconds, 1 decimal place), and minimum wait time (seconds, 1 decimal place), computed only from vehicles that have both an enter time and a leave time.
3. THE Results_View SHALL sort the vehicle table by enter time ascending as the default sort order, with clickable column headers that toggle between ascending and descending sort on repeated clicks.
4. THE Results_View SHALL display the output video file path with a button to open the containing folder in Windows Explorer.
5. WHEN the user clicks a "New session" button on the Results_View, THE GUI_Application SHALL return to the Video_Input_Panel with all settings preserved from the previous session (confidence threshold, OCR toggle, OCR language, OCR interval, output path, and display preferences).
6. WHILE OCR is disabled, THE Results_View SHALL hide the Plate Text and Confidence columns from the vehicle table.
7. IF Pipeline processing completes with zero tracked vehicles, THEN THE Results_View SHALL display an empty-state message indicating that no vehicles were detected in the video and show the "New session" button to allow the operator to return to the Video_Input_Panel.
8. IF a tracked vehicle has an enter time but no leave time (vehicle remained in frame at end of processing), THEN THE Results_View SHALL include that vehicle in the table with Leave Time displayed as "—" and Wait Time displayed as "—", and SHALL exclude that vehicle from summary statistic calculations.

### Requirement 5: Settings and configuration persistence

**User Story:** As a station operator, I want my preferred settings to persist between application sessions, so that I do not need to reconfigure detection parameters each time.

#### Acceptance Criteria

1. WHEN the user modifies any setting (confidence threshold, OCR toggle, OCR language, OCR interval, output path, window size, or window position), THE GUI_Application SHALL save the complete set of current settings to the local JSON configuration file within 2 seconds of the modification.
2. WHEN the GUI_Application launches, THE GUI_Application SHALL load previously saved settings from the configuration file and apply them to the Video_Input_Panel controls before the Video_Input_Panel is displayed to the user.
3. IF the configuration file is missing, cannot be parsed as valid JSON, or contains values outside their valid ranges (e.g., confidence threshold outside 0.1–1.0), THEN THE GUI_Application SHALL use default values for all settings (confidence threshold 0.5, OCR disabled, OCR language "en", OCR interval 10, output path "output.mp4" in input directory) and create a new valid configuration file.
4. THE GUI_Application SHALL store the configuration file at %LOCALAPPDATA%\OpusLaneSight\settings.json, creating the directory if it does not exist.
5. IF the configuration file directory or file is not writable, THEN THE GUI_Application SHALL operate with in-memory settings for the current session and display a non-blocking warning message indicating that settings cannot be persisted.

### Requirement 6: Pipeline integration without modification

**User Story:** As a developer, I want the GUI to orchestrate the existing Python pipeline modules without modifying them, so that the GUI remains a separate layer that does not introduce regressions in the core detection logic.

#### Acceptance Criteria

1. THE GUI_Application SHALL import and invoke the existing Pipeline modules (VehicleDetector, VehicleTracker, PlateOCR, AppearanceExtractor) directly without modifying the module source files.
2. THE GUI_Application SHALL pass user-configured parameters (confidence threshold, OCR language list, OCR frame interval, plate model path, no-ocr flag) to the Pipeline module constructors and functions using the same parameter names and types accepted by the `process_video` function in main.py.
3. WHEN a frame has been processed by the Pipeline, THE Worker_Thread SHALL emit a signal containing the annotated frame image, current frame index, and active track count within 200 milliseconds of frame completion so that the Processing_View can update the display without perceived stutter.
4. THE GUI_Application SHALL capture Pipeline console output (print statements) by redirecting stdout and stderr to an in-memory buffer, and SHALL display the captured text in a log panel accessible from the GUI rather than allowing it to appear in a background console window, retaining at most the most recent 10,000 lines.
5. IF a Pipeline module raises an unhandled exception during processing, THEN THE Worker_Thread SHALL stop processing, emit an error signal containing the exception message, and THE GUI_Application SHALL display the error message to the user while remaining responsive and allowing a new processing run to be started.
6. IF the user cancels processing before the video completes, THEN THE Worker_Thread SHALL stop invoking Pipeline modules within 1 second, release the video resource, and THE GUI_Application SHALL return to a ready state without crashing or displaying incomplete results as final.

### Requirement 7: Opus brand compliance

**User Story:** As a product stakeholder, I want the GUI to reflect the Opus brand identity, so that the application looks professional and consistent with other Opus products.

#### Acceptance Criteria

1. THE GUI_Application SHALL use the Opus color palette as primary UI colors: teal-dark (#004851) for the header, teal (#00968F) for primary action buttons, green (#93D500) for success states, blue (#00A0E0) for informational elements, orange (#FF8200) for warnings only, charcoal (#131E29) for primary text, and gray (#54565A) for secondary text.
2. THE GUI_Application SHALL use the Roboto font family for all text elements with the following type hierarchy: page titles at 36–44px 700-weight, section titles at 24–28px 700-weight, card titles at 16–18px 600-weight, body text at 14–16px 400-weight, metric values at 32–48px 700-weight, and captions at 12–13px 400-weight.
3. THE GUI_Application SHALL use card-based layout with white (#FFFFFF) background, 1px solid border at rgba(19, 30, 41, 0.08), 14px border radius, and box-shadow of 0 8px 24px rgba(19, 30, 41, 0.08) for content grouping.
4. THE GUI_Application SHALL display the official Opus logo in the header at a minimum height of 36px without modification, stretching, recoloring, or applied effects, and maintain clear space around the logo at least equal to the width of the letter "S" in the OPUS wordmark.
5. THE GUI_Application SHALL use sentence case for all headings and labels.
6. THE GUI_Application SHALL use the brand gradient (linear-gradient at 135deg, #004851 at 0%, #00968F at 58%, #93D500 at 100%) for the application header bar.

### Requirement 8: Error handling and input validation

**User Story:** As a station operator, I want clear feedback when something goes wrong, so that I can correct the issue and continue working.

#### Acceptance Criteria

1. IF the user attempts to start processing without a YOLO model file (yolov8n.pt) available in the application's working directory or a user-specified model path, THEN THE GUI_Application SHALL display an error dialog explaining that the vehicle detection model is missing and suggest placing it in the application directory or selecting it via settings.
2. IF the selected output path is not writable (directory does not exist or permission denied), THEN THE GUI_Application SHALL display an error message before processing begins and allow the user to choose a different output path.
3. IF the Pipeline encounters a frame-read failure during processing, THEN THE GUI_Application SHALL skip the frame, increment an error counter displayed in the Processing_View, and continue processing subsequent frames.
4. WHEN processing completes with skipped frames, THE Results_View SHALL display a warning note indicating how many frames were skipped out of the total frame count during processing.
5. IF the user provides a Confidence_Threshold value outside the range 0.1 to 1.0 via manual text entry, THEN THE GUI_Application SHALL clamp the value to the nearest valid boundary (0.1 or 1.0) and display a tooltip indicating the valid range is 0.1 to 1.0.
6. IF the number of consecutive frame-read failures exceeds 100, THEN THE GUI_Application SHALL abort processing, display an error message indicating the video may be corrupt or unreadable beyond that point, and return to the Video_Input_Panel.

### Requirement 9: Window management and system integration

**User Story:** As a Windows user, I want the application to behave like a native Windows application with standard window controls and system tray behavior.

#### Acceptance Criteria

1. THE GUI_Application SHALL support standard Windows window controls: minimize, maximize/restore, and close.
2. WHEN the user closes the window during active processing, THE GUI_Application SHALL display a confirmation dialog with two options: "Cancel and exit" which stops the Worker_Thread, releases resources, and closes the application, or "Continue processing" which dismisses the dialog and resumes processing with the window remaining open.
3. THE GUI_Application SHALL set the window title to "Opus LaneSight" followed by a dash-separated state indicator: "Ready" when the Video_Input_Panel is displayed, "Processing [filename]" when processing is active, and "Results" when the Results_View is displayed.
4. THE GUI_Application SHALL use a custom application icon derived from or consistent with the Opus brand (not the default framework icon).
5. THE GUI_Application SHALL support drag-and-drop of video files with extensions MP4, AVI, MOV, or MKV onto the main window as an alternative to the file dialog for input selection, applying the same validation as the file dialog selection path defined in Requirement 2.
6. IF the user drops a file onto the main window that does not have an accepted video extension (MP4, AVI, MOV, MKV) or cannot be opened by OpenCV, THEN THE GUI_Application SHALL reject the drop and display an error message indicating the file type is unsupported or the file is unreadable.

### Requirement 10: Future extensibility accommodation

**User Story:** As a developer, I want the GUI architecture to accommodate planned future features without requiring a full rewrite, so that new capabilities can be added incrementally.

#### Acceptance Criteria

1. THE GUI_Application SHALL use a navigation structure (sidebar or tab bar) that displays entries for the current three views (Input, Processing, Results) and can hold at least 6 total navigation entries without layout overflow or scrolling, so that future views such as a dashboard view, stream configuration view, and zone editor view can be added by inserting a new entry.
2. THE GUI_Application SHALL define video input as an abstraction that accepts a source identifier string (file path or URI), and THE Processing_View SHALL consume frame data exclusively through Worker_Thread signals without directly referencing file-system APIs, so that replacing the file-based source with an RTSP or RTMP stream requires changes only to the input abstraction and not to the Processing_View.
3. THE GUI_Application SHALL organize its source code into separate modules for: main window/navigation, input panel, processing view, results view, settings, worker thread, and brand theme, each in its own Python file within a gui/ package directory.
4. THE GUI_Application SHALL use Qt signal/slot connections for all communication between the Worker_Thread and GUI views, with no direct method calls from the Worker_Thread to view widgets.
5. THE GUI_Application SHALL implement each view (Video_Input_Panel, Processing_View, Results_View) as an independent widget class that does not import or directly reference other view modules, so that a new view can be added without modifying existing view source files.

### Requirement 11: Live stream input

**User Story:** As a station operator, I want to process a live RTSP/RTMP/HTTP camera stream instead of a file, so that I can monitor station flow in real time.

#### Acceptance Criteria

1. THE Video_Input_Panel SHALL provide an Input_Source_Mode selector with two mutually exclusive options, "Video file" and "Live stream", defaulting to "Video file".
2. WHEN the user selects the "Live stream" Input_Source_Mode, THE Video_Input_Panel SHALL display a stream URL text field that accepts URLs beginning with the rtsp://, rtmp://, http://, or https:// scheme up to a maximum of 2048 characters, and SHALL hide the file selection control.
3. WHILE the "Live stream" Input_Source_Mode is selected, THE Video_Input_Panel SHALL disable the file selection control such that file input and stream input cannot both be active for a single Processing_Session.
4. WHEN the user enters a stream URL that begins with rtsp://, rtmp://, http://, or https:// and clicks "Start processing", THE GUI_Application SHALL pass the stream URL to the Pipeline as the `stream_url` parameter and SHALL pass `video_path` as empty.
5. IF the user clicks "Start processing" in "Live stream" Input_Source_Mode with a stream URL field that is empty or contains only whitespace, THEN THE GUI_Application SHALL display an inline error message indicating that a stream URL is required, SHALL retain the field state, and SHALL NOT start processing.
6. WHILE processing a Stream_Source, THE Processing_View SHALL display an indeterminate progress indicator instead of a percentage progress bar, because the total frame count of a Stream_Source is unknown.
7. WHILE processing a Stream_Source, THE Processing_View SHALL update the live statistics for elapsed time in seconds, active vehicle count, and effective frames-per-second at least once per second.
8. WHEN the Stream_Source is interrupted, THE Processing_View SHALL display a reconnection status message indicating the current reconnection attempt number out of a maximum of 5 attempts, retried at 2-second intervals, and SHALL update this message within 1 second of each new attempt.
9. IF the Stream_Source cannot be re-established after 5 reconnection attempts, THEN THE GUI_Application SHALL stop processing, display a message indicating the stream was lost, and switch to the Results_View showing the tracks collected before the interruption.
10. THE Processing_View SHALL provide a "Stop" control that, when clicked during Stream_Source processing, stops the Worker_Thread within 3 seconds, releases stream resources, and switches to the Results_View showing the tracks collected up to that point.
11. WHERE the user enables recording for a Stream_Source by specifying an output path, THE GUI_Application SHALL record the annotated stream to that output file while processing continues indefinitely.
12. IF the user clicks "Start processing" in "Live stream" Input_Source_Mode with a non-empty stream URL that does not begin with rtsp://, rtmp://, http://, or https://, THEN THE GUI_Application SHALL display an inline error message indicating that a supported stream URL scheme is required, SHALL retain the entered URL, and SHALL NOT start processing.
13. WHEN the user starts processing a Stream_Source and before the first frame is received, THE Processing_View SHALL display a connecting status message identifying the target stream URL.

### Requirement 12: Detection backend selection

**User Story:** As a station operator, I want to choose between the local YOLOv8 detector and the AWS Rekognition cloud detector, so that I can match detection to the available hardware or cloud budget.

#### Acceptance Criteria

1. THE Video_Input_Panel SHALL provide a Detector_Backend selector with two mutually exclusive options, "Local YOLOv8" and "AWS Rekognition", defaulting to "Local YOLOv8".
2. WHEN the user selects the "AWS Rekognition" Detector_Backend, THE Video_Input_Panel SHALL display an editable AWS_Region text field of 1 to 64 characters pre-filled with "us-east-1".
3. WHILE the "Local YOLOv8" Detector_Backend is selected, THE Video_Input_Panel SHALL hide the AWS_Region field.
4. WHEN the user starts processing, THE GUI_Application SHALL pass the value "yolo" for the "Local YOLOv8" option or "rekognition" for the "AWS Rekognition" option, together with the AWS_Region value, to the Pipeline `process_video` function using the `detector_backend` and `aws_region` parameter names.
5. IF the user clicks "Start processing" with the "AWS Rekognition" Detector_Backend selected and an AWS_Region field that is empty or contains only whitespace, THEN THE GUI_Application SHALL display an inline error message indicating that an AWS region is required, SHALL retain the current selections, and SHALL NOT start processing.
6. IF an AWS Rekognition API call fails due to missing or invalid AWS credentials, THEN THE GUI_Application SHALL stop processing, display an error message identifying the failure as an AWS credentials error, retain the current selections, and return to the Video_Input_Panel.
7. IF an AWS Rekognition API call fails due to a region, network, or service error, THEN THE GUI_Application SHALL stop processing, display an error message describing the AWS API failure, retain the current selections, and return to the Video_Input_Panel.
8. THE Plate_Text_Reading capability SHALL default to disabled and SHALL require explicit opt-in by the user before any plate text is read by either EasyOCR or AWS Rekognition DetectText.
9. WHERE the "AWS Rekognition" Detector_Backend is selected with Plate_Text_Reading enabled, THE Video_Input_Panel SHALL display the privacy note from Requirement 1.5 indicating that reading plate text is opt-in and used for development and testing only, consistent with the privacy-preserving positioning.

### Requirement 13: Detection interval control

**User Story:** As a station operator, I want to run detection only every N frames, so that I can reduce GPU load or AWS API cost while Kalman prediction fills the gaps.

#### Acceptance Criteria

1. THE Video_Input_Panel SHALL provide a Detection_Interval numeric control with a minimum value of 1, a maximum value of 60, a step increment of 1, and a default value of 1.
2. WHEN the user starts processing, THE GUI_Application SHALL pass the current Detection_Interval value as a positive integer to the Pipeline `process_video` function using the `detect_interval` parameter name.
3. WHILE the "AWS Rekognition" Detector_Backend is selected, THE Video_Input_Panel SHALL display a visible recommendation indicating the Detection_Interval should be set between 5 and 10 to reduce API calls and cost.
4. IF the user enters a Detection_Interval value below 1 via manual text entry, THEN THE GUI_Application SHALL clamp the value to 1, retain the control in an editable state, and display a tooltip indicating the valid range is 1 to 60.
5. IF the user enters a Detection_Interval value above 60 via manual text entry, THEN THE GUI_Application SHALL clamp the value to 60, retain the control in an editable state, and display a tooltip indicating the valid range is 1 to 60.
6. IF the user enters a non-integer or non-numeric Detection_Interval value via manual text entry, THEN THE GUI_Application SHALL reject the entry, restore the most recent valid integer value, and display a tooltip indicating the valid range is 1 to 60.

### Requirement 14: Deduplicated results display

**User Story:** As a station operator, I want results to merge duplicate detections of the same plate, so that each physical vehicle appears once in the wait-time table.

#### Acceptance Criteria

1. WHEN Plate_Text_Reading is enabled and Pipeline processing completes, THE Results_View SHALL display the Plate_Deduplication results in which every set of tracks whose plate text is identical, or is matched after normalizing the OCR-confusable characters (O/0, I/1, S/5, B/8), is merged into exactly one row.
2. THE Results_View SHALL display each merged row using a frame span from the smallest first_frame to the largest last_frame in the group, the enter and leave times derived from those frames, the summed hit counts of the group, and the single best plate text selected by the Pipeline for the group.
3. IF a track has no plate text or plate text shorter than 3 characters, THEN THE Results_View SHALL display that track as its own row and SHALL NOT merge it with any other track.
4. WHILE Plate_Text_Reading is disabled, THE Results_View SHALL display every track as a separate row without Plate_Deduplication, because no plate text is available to merge on.
5. THE Results_View SHALL compute the total vehicles tracked and the summary statistics from the deduplicated set of rows when Plate_Deduplication has been applied.

### Requirement 15: No-output mode toggle

**User Story:** As a station operator, I want to disable writing the annotated output video, so that processing runs faster when I only need the results table.

#### Acceptance Criteria

1. THE Video_Input_Panel SHALL provide a No_Output_Mode toggle that defaults to disabled when no persisted value is available from the configuration mechanism defined in Requirement 5.
2. WHILE No_Output_Mode is enabled, THE Video_Input_Panel SHALL disable the output file path selector control such that the operator cannot edit, browse to, or change the output path.
3. WHILE No_Output_Mode is disabled, THE Video_Input_Panel SHALL enable the output file path selector control so the operator can edit and browse to the output path.
4. WHEN the user starts processing with No_Output_Mode enabled, THE GUI_Application SHALL invoke the Pipeline with output_path set to None (equivalent to the existing `--no-output` flag) such that no annotated output video file is written.
5. WHILE No_Output_Mode is enabled, THE Results_View SHALL omit the output video file path display and the open-containing-folder control defined in Requirement 4.4, and SHALL display text indicating that no output video was written.
6. WHEN the user changes the No_Output_Mode toggle state, THE GUI_Application SHALL persist the new toggle state using the configuration mechanism defined in Requirement 5 within 2 seconds of the change so that it is restored on the next application session.
