# Requirements Document

## Introduction

The Station Identification feature lets an operator assign a user-definable station identifier to a running Opus LaneSight instance. The identifier names which physical inspection station the instance represents. Today the data model references a station identifier as a hard-coded literal (for example, "demo_station_01") embedded in vehicle sessions, zone events, and station metric snapshots. This feature replaces that implicit literal with an explicit, operator-configured, persisted value that is surfaced in the GUI and carried through into generated reports and future API/wait-time output.

The feature has three concerns: (1) let the operator view and edit a station identifier and an optional human-readable display name through the GUI, (2) persist these values so they survive application restarts, and (3) propagate the active station identifier into every record and report the instance produces so downstream consumers can attribute data to the correct station.

This document covers configuration, validation, persistence, and propagation of the station identifier. It does not define the visual styling of the wait-time output, the schema of any future remote API, or multi-station management within a single instance.

## Glossary

- **GUI_Application**: The existing Opus LaneSight PySide6/PyQt6 desktop application that orchestrates the detection pipeline and displays results, as defined in the lanesight-gui spec.
- **Station_Identifier**: An operator-defined string that uniquely names the inspection station the running instance is assigned to (for example, "demo_station_01"). This is the canonical machine-readable value stored in records and reports.
- **Station_Display_Name**: An optional operator-defined, human-readable label for the station (for example, "Demo Inspection Station") shown in user-facing surfaces.
- **Station_Config**: The persisted set of values comprising the Station_Identifier and the Station_Display_Name for the running instance.
- **Station_Settings_View**: The GUI section or dialog where the operator views and edits the Station_Identifier and Station_Display_Name.
- **Config_Store**: The local JSON configuration file used by the GUI_Application to persist settings, located at %LOCALAPPDATA%\OpusLaneSight\settings.json, as defined in the lanesight-gui spec.
- **Vehicle_Session**: A record of an anonymous tracked vehicle's passage through the station, which includes a station identifier field.
- **Zone_Event**: A record of a vehicle entering or exiting a defined zone, which includes a station identifier field.
- **Station_Metric_Snapshot**: An aggregated record of station-level metrics at a point in time, which includes a station identifier field.
- **Report**: Any operator- or instance-generated artifact summarizing processing output, including the results table, exported result files, and the station summary.
- **Wait_Time_Output**: The machine-readable wait-time payload (for example, a JSON object) the instance produces for public or programmatic consumption.
- **Default_Station_Identifier**: The fallback Station_Identifier value "demo_station_01" used when no operator-configured value is available.

## Requirements

### Requirement 1: Configure the station identifier

**User Story:** As a station operator, I want to set a station identifier for this instance, so that the data this instance produces is attributed to the correct station.

#### Acceptance Criteria

1. THE Station_Settings_View SHALL provide an editable text field for the Station_Identifier.
2. THE Station_Settings_View SHALL provide an editable text field for the Station_Display_Name.
3. THE Station_Settings_View SHALL provide a save control that the operator activates to submit the entered Station_Identifier and Station_Display_Name.
4. WHEN the Station_Settings_View is opened, THE GUI_Application SHALL display the currently active Station_Identifier and Station_Display_Name in their respective fields within 2 seconds.
5. WHEN the operator activates the save control with a valid Station_Identifier and a valid Station_Display_Name, THE GUI_Application SHALL set the entered values as the active Station_Config for the running instance.
6. WHEN the operator activates the save control and the resulting Station_Config differs from the currently active Station_Config, THE GUI_Application SHALL display a confirmation message indicating that the station configuration was updated and keep that message visible for at least 3 seconds or until the operator dismisses it.

### Requirement 2: Validate the station identifier

**User Story:** As a station operator, I want the application to reject malformed station identifiers, so that downstream records and reports contain consistent, usable identifiers.

#### Acceptance Criteria

1. THE GUI_Application SHALL treat a Station_Identifier as valid only WHEN it is 1 to 64 characters long and contains only lowercase letters (a-z), digits (0-9), hyphens, and underscores.
2. WHEN the operator saves a valid Station_Identifier and a valid Station_Display_Name, THE GUI_Application SHALL set them as the active Station_Config and display a confirmation that the station configuration was saved.
3. IF the operator saves a Station_Identifier that is empty or contains only whitespace, THEN THE GUI_Application SHALL reject the save, display an inline error message indicating that a station identifier is required, and retain the current active Station_Config unchanged.
4. IF the operator saves a Station_Identifier of 1 to 64 characters that contains characters outside lowercase letters, digits, hyphens, and underscores, THEN THE GUI_Application SHALL reject the save, display an inline error message describing the allowed character set, and retain the current active Station_Config unchanged.
5. IF the operator saves a Station_Identifier longer than 64 characters, THEN THE GUI_Application SHALL reject the save, display an inline error message indicating the 64-character maximum, and retain the current active Station_Config unchanged.
6. THE GUI_Application SHALL treat a Station_Display_Name as valid only WHEN it is 0 to 128 characters long.
7. IF the operator saves a Station_Display_Name longer than 128 characters, THEN THE GUI_Application SHALL reject the save, display an inline error message indicating the 128-character maximum, and retain the current active Station_Config unchanged.
8. WHERE the operator leaves the Station_Display_Name empty or whitespace-only, THE GUI_Application SHALL use the Station_Identifier as the Station_Display_Name for user-facing surfaces.

### Requirement 3: Persist the station configuration

**User Story:** As a station operator, I want my station identifier to persist across restarts, so that I configure it once per instance rather than on every launch.

#### Acceptance Criteria

1. WHEN the operator saves a valid Station_Config, THE GUI_Application SHALL write the Station_Identifier and Station_Display_Name to the Config_Store within 2 seconds of the save action.
2. WHEN the GUI_Application launches, THE GUI_Application SHALL load the persisted Station_Config from the Config_Store and set it as the active Station_Config before the first Report or Wait_Time_Output is produced.
3. IF the Config_Store contains no Station_Config, THEN THE GUI_Application SHALL set the active Station_Identifier to the Default_Station_Identifier and set the active Station_Display_Name equal to the Default_Station_Identifier.
4. IF the Config_Store cannot be read or parsed at launch, THEN THE GUI_Application SHALL set the active Station_Identifier to the Default_Station_Identifier and display a non-blocking warning indicating that the saved station configuration could not be read and a default was applied.
5. IF the persisted Station_Identifier fails the validation rules in Requirement 2, THEN THE GUI_Application SHALL set the active Station_Identifier to the Default_Station_Identifier and display a non-blocking warning indicating that the saved station identifier was invalid and a default was applied.
6. IF the Config_Store is not writable, THEN THE GUI_Application SHALL retain the Station_Config in memory for the current session and display a non-blocking warning indicating that the station identifier cannot be persisted.

### Requirement 4: Display the active station

**User Story:** As a station operator, I want the active station identity shown in the interface, so that I can confirm at a glance which station this instance represents.

#### Acceptance Criteria

1. WHILE an active Station_Config is loaded, THE GUI_Application SHALL display the active Station_Display_Name in the application header area on every view, rendering it within 2 seconds of each view becoming visible.
2. IF the active Station_Display_Name exceeds 40 characters, THEN THE GUI_Application SHALL truncate the displayed value to 40 characters with a trailing ellipsis and expose the full Station_Display_Name to the operator on hover or focus.
3. WHERE the Station_Display_Name differs from the Station_Identifier, THE GUI_Application SHALL display the active Station_Identifier as a distinct, non-truncated text field within the Station_Settings_View.
4. WHEN the operator changes the active Station_Config, THE GUI_Application SHALL update the displayed Station_Display_Name in the header area within 2 seconds.
5. IF no active Station_Config is loaded, THEN THE GUI_Application SHALL display a placeholder indicating no station is selected in the header area and SHALL leave the Station_Identifier field in the Station_Settings_View empty.

### Requirement 5: Attach the station identifier to produced records

**User Story:** As a program operations analyst, I want every record produced by an instance to carry its station identifier, so that I can attribute sessions, events, and metrics to the correct station.

#### Acceptance Criteria

1. WHEN the GUI_Application produces a Vehicle_Session, THE GUI_Application SHALL set the station identifier field of that Vehicle_Session to the active Station_Identifier in effect at the moment that Vehicle_Session is created.
2. WHEN the GUI_Application produces a Zone_Event, THE GUI_Application SHALL set the station identifier field of that Zone_Event to the active Station_Identifier in effect at the moment that Zone_Event is created.
3. WHEN the GUI_Application produces a Station_Metric_Snapshot, THE GUI_Application SHALL set the station identifier field of that Station_Metric_Snapshot to the active Station_Identifier in effect at the moment that Station_Metric_Snapshot is created.
4. THE GUI_Application SHALL set the station identifier field of every produced record to a non-empty value equal to the active Station_Identifier captured at the moment that record is created.
5. IF the active Station_Identifier changes after a record has been created, THEN THE GUI_Application SHALL retain the station identifier value already assigned to that record without modifying it.

### Requirement 6: Include the station identity in reports

**User Story:** As a station operator, I want generated reports to include the station identity, so that exported and displayed results are clearly attributed to a station.

#### Acceptance Criteria

1. WHEN the GUI_Application generates a Report, THE GUI_Application SHALL include the active Station_Identifier in that Report.
2. WHEN the GUI_Application generates a Report, THE GUI_Application SHALL include the active Station_Display_Name in that Report.
3. WHEN the GUI_Application exports a Report to a file, THE GUI_Application SHALL include the active Station_Identifier as a field in the exported file.
4. WHEN the GUI_Application displays results in the Results_View, THE GUI_Application SHALL include the active Station_Display_Name in the displayed results header.
5. IF no active Station_Config is loaded when the GUI_Application generates or exports a Report, THEN THE GUI_Application SHALL include the Default_Station_Identifier in that Report.

### Requirement 7: Include the station identifier in wait-time output

**User Story:** As a developer building public-facing and programmatic consumers, I want the station identifier included in the wait-time output, so that future API consumers can route and label wait-time data by station.

#### Acceptance Criteria

1. WHEN the GUI_Application produces a Wait_Time_Output, THE GUI_Application SHALL include the active Station_Identifier, valued as of the time the Wait_Time_Output is produced, as a field in that Wait_Time_Output.
2. WHEN the GUI_Application produces a Wait_Time_Output, THE GUI_Application SHALL include the active Station_Display_Name, valued as of the time the Wait_Time_Output is produced, as a field in that Wait_Time_Output.
3. THE GUI_Application SHALL represent the Station_Identifier in the Wait_Time_Output using a fixed field name that remains unchanged across application releases.
4. THE GUI_Application SHALL represent the Station_Display_Name in the Wait_Time_Output using a fixed field name that remains unchanged across application releases.
