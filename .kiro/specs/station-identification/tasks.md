# Implementation Plan: Station Identification

## Overview

This plan implements the Station Identification feature by extending the existing `gui/` PySide6 application. It adds Qt-free validation helpers, an immutable `StationConfig` value object, a `StationController` single source of truth, a `StationSettingsView`, header integration in `MainWindow`, and station-identifier propagation into produced records, reports, and wait-time output. Work proceeds from pure logic (validation, value object) outward to controller, persistence, UI wiring, and propagation, so each step builds on the previous and ends fully integrated. Property-based tests (Hypothesis) validate the 12 correctness properties; unit and integration tests cover widget and launch behavior.

Implementation language: Python (matches the existing `gui/` codebase and the design document).

## Tasks

- [x] 1. Add station validation helpers and the StationConfig value object
  - [x] 1.1 Implement pure validation functions in `gui/station_validation.py`
    - Define `DEFAULT_STATION_IDENTIFIER = "demo_station_01"`, `IDENTIFIER_MAX_LEN = 64`, `DISPLAY_NAME_MAX_LEN = 128`, `HEADER_DISPLAY_MAX_LEN = 40`, and the `_IDENTIFIER_RE` regex
    - Implement `IdentifierError` enum (`EMPTY`, `TOO_LONG`, `BAD_CHARSET`)
    - Implement `validate_station_identifier`, `validate_display_name`, `effective_display_name`, and `header_label` with the check ordering described in the design
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.2_

  - [x] 1.2 Add the StationConfig dataclass to `gui/models.py`
    - Implement `@dataclass(frozen=True) StationConfig` with `identifier` and `display_name` fields
    - Add the `effective_display_name` property (delegating to `station_validation.effective_display_name`) and the `default()` classmethod
    - _Requirements: 2.8, 3.3, 5.5_

  - [x] 1.3 Write property test for Station_Identifier validation
    - **Property 1: Station_Identifier validation**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5**

  - [x] 1.4 Write property test for Station_Display_Name validation
    - **Property 2: Station_Display_Name validation**
    - **Validates: Requirements 2.6, 2.7**

  - [x] 1.5 Write property test for effective display name fallback
    - **Property 3: Effective display name fallback**
    - **Validates: Requirements 2.8**

  - [x] 1.6 Write property test for header truncation
    - **Property 4: Header truncation**
    - **Validates: Requirements 4.2**

- [x] 2. Extend persistence for station fields
  - [x] 2.1 Add station fields to AppSettings and SettingsManager validation
    - Add `station_id` and `station_display_name` fields to the `AppSettings` dataclass in `gui/models.py`
    - Extend `SettingsManager._validate` to enforce type/shape: `station_id` defaults to `"demo_station_01"` when absent/non-string; `station_display_name` must be a string of length <= 128 (truncate longer values, fall back to `station_id` for non-strings)
    - Ensure load/save round-trips both fields through `settings.json`
    - _Requirements: 3.1, 3.2_

  - [x] 2.2 Write unit tests for SettingsManager station field handling
    - Test default substitution when fields absent, display-name truncation at 128, and non-string fallback
    - _Requirements: 3.1, 3.2_

- [x] 3. Implement the StationController
  - [x] 3.1 Create `gui/station_controller.py` with active-config management
    - Implement `StationController(QObject)` with `station_changed` and `warning` signals
    - Implement `active()`, `active_identifier()`, and `set_active(config)` (validate, persist via `SettingsManager`, emit `station_changed`, return change flag, emit `warning` when store is read-only, raise `ValueError` on invalid input)
    - Implement `_load_active()` that loads from settings and revalidates the identifier: default when absent (3.3), default + warning on read/parse error (3.4), default + warning when persisted id fails Requirement 2 (3.5)
    - _Requirements: 1.5, 1.6, 2.2, 3.2, 3.3, 3.4, 3.5, 3.6, 5_

  - [x] 3.2 Write property test for save sets the active configuration
    - **Property 5: Save sets the active configuration**
    - **Validates: Requirements 1.5, 2.2**

  - [x] 3.3 Write property test for change detection
    - **Property 6: Change detection**
    - **Validates: Requirements 1.6**

  - [x] 3.4 Write property test for persistence round-trip
    - **Property 7: Persistence round-trip**
    - **Validates: Requirements 3.1, 3.2**

  - [x] 3.5 Write property test for invalid persisted identifier fallback
    - **Property 8: Invalid persisted identifier falls back to default**
    - **Validates: Requirements 3.5**

  - [x] 3.6 Write unit tests for StationController fallback and warning paths
    - Test default when store empty (3.3), corrupt store -> default + warning (3.4), read-only store -> in-memory retention + warning (3.6), active config set at construction before producers run (3.2)
    - _Requirements: 3.2, 3.3, 3.4, 3.6_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Build the StationSettingsView
  - [x] 5.1 Create `gui/station_settings_view.py`
    - Build identifier `QLineEdit` (maxLength 64), display-name `QLineEdit` (maxLength 128), "Save station" button, inline error label (orange), and confirmation label/toast, following `ui_guidelines.md`
    - Subscribe to `controller.station_changed`; implement `showEvent` to populate fields from the active config within 2s and leave the identifier field empty when no active config (4.5)
    - Implement `on_save_clicked`: validate both fields, show inline error and leave active config unchanged on failure (2.3-2.7); on success build a `StationConfig`, call `controller.set_active`, show saved/updated confirmation kept visible >=3s or until dismissed (1.5, 1.6, 2.2)
    - Show the identifier as a distinct, non-truncated field when it differs from the display name (4.3)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.2, 2.3, 2.4, 2.5, 2.7, 4.3, 4.5_

  - [x] 5.2 Write unit tests for StationSettingsView
    - Test fields/button exist (1.1-1.3), fields populated on open (1.4), inline error on invalid save and confirmation on changed save (1.6, 2.2), distinct non-truncated identifier when differing from display name (4.3), empty identifier field when no active config (4.5)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.2, 4.3, 4.5_

- [x] 6. Integrate the active station into the MainWindow header
  - [x] 6.1 Wire StationController and station label into `gui/main_window.py`
    - Construct `StationController(self._settings)` in `MainWindow.__init__` and connect `station_changed` -> `_update_station_label` and `warning` -> `_show_station_warning`
    - Add a right-aligned station label in `_build_header()` after the existing `addStretch(1)`, using white header text
    - Implement `_update_station_label` to apply `header_label()` truncation at 40 chars with full value as tooltip (4.2), render the display name on every view (4.1, 4.4), and show the "No station selected" placeholder when no active config (4.5)
    - Implement `_show_station_warning` to display non-blocking warnings (3.4, 3.5, 3.6)
    - Register `StationSettingsView` in the existing view stack
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

  - [x] 6.2 Write unit tests for MainWindow header station rendering
    - Test display name rendered on every view (4.1), header updates on `station_changed` (4.4), placeholder when no active config (4.5), 40-char truncation with full value in tooltip (4.2)
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Propagate the station identifier into records, reports, and wait-time output
  - [x] 8.1 Implement record producers that capture the active identifier by value
    - Implement `build_vehicle_session`, `build_zone_event`, and `build_station_metric_snapshot` so each sets `station_id` from the active identifier captured at creation (plain `str`, immutable)
    - Inject the active identifier via `StationController.active_identifier()` (or a `station_id_provider: Callable[[], str]`) at the moment each record is created
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.2 Write property test for produced records capturing the active identifier
    - **Property 9: Produced records capture the active identifier**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [x] 8.3 Write property test for record identifier immutability
    - **Property 10: Record identifier immutability**
    - **Validates: Requirements 5.5**

  - [x] 8.4 Implement the report builder/exporter with station identity
    - Implement `build_report(content, config)` including the active `Station_Identifier` and effective display name, falling back to `DEFAULT_STATION_IDENTIFIER` when `config` is `None` (6.1, 6.2, 6.5)
    - Ensure exported report files carry `station_id` as a field (6.3)
    - Add the active display name to the `ResultsView.display_results` header, reading from the injected `StationController` (6.4)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 8.5 Write property test for reports including the station identity
    - **Property 11: Reports include the station identity**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.5**

  - [x] 8.6 Write unit test for ResultsView station display name
    - Test the active display name appears in the results header (6.4)
    - _Requirements: 6.4_

  - [x] 8.7 Implement the wait-time output builder with fixed field names
    - Define `WAIT_TIME_STATION_ID_FIELD = "station_id"` and `WAIT_TIME_STATION_DISPLAY_NAME_FIELD = "station_display_name"`
    - Implement `build_wait_time_output(metrics, config)` embedding the active identifier and effective display name under the fixed field names, valued as of production time (7.1, 7.2, 7.3, 7.4)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 8.8 Write property test for wait-time output fields
    - **Property 12: Wait-time output includes the station identity under fixed field names**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

- [x] 9. Integration and launch wiring
  - [x] 9.1 Wire record/report/wait-time producers to the StationController
    - Pass the `StationController` (or `station_id_provider`) into the record producers, report builder/exporter, and wait-time builder so they read the active identifier at creation time
    - Ensure the controller is constructed at launch before the first record/report/wait-time output is produced (3.2)
    - _Requirements: 3.2, 5.1, 5.2, 5.3, 6.1, 7.1_

  - [x] 9.2 Write integration test for the launch and save-reload flow
    - Construct the controller from the Config_Store, assert producers read a set non-empty identifier before the first report/wait-time output (3.2), and verify save -> persist -> fresh reload yields the saved config and updates the header via `station_changed`
    - _Requirements: 3.1, 3.2, 4.4_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific requirements for traceability; property test sub-tasks reference the design property they validate.
- Property-based tests use Hypothesis (`tests/test_station_properties.py`) with `@settings(max_examples=100)` and the tag `# Feature: station-identification, Property {N}: {title}`.
- Tests run headless via `QT_QPA_PLATFORM=offscreen`; no new runtime dependencies are introduced.
- Checkpoints ensure incremental validation at natural integration boundaries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5", "1.6", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "5.1", "8.1"] },
    { "id": 4, "tasks": ["5.2", "6.1", "8.2", "8.3", "8.4", "8.7"] },
    { "id": 5, "tasks": ["6.2", "8.5", "8.6", "8.8", "9.1"] },
    { "id": 6, "tasks": ["9.2"] }
  ]
}
```
