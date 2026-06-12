# Requirements Document

## Introduction

The Public Stats Dashboard is a static demo website, hosted using Amazon S3 static website hosting, that demonstrates the public-facing motorist wait-time experience for the Opus LaneSight program. It is a thin, demoable hackathon prototype: a single page that lets a viewer pick an inspection station from a dropdown and see that station's current wait-time information presented as a motorist-friendly public wait-time card.

The site does not compute any statistics itself. It is a read-only consumer of the existing Station Statistics API (defined in the `station-stats-api` spec). It calls `GET /stations` to discover which stations have published a snapshot and populate the station selector, and `GET /stations/{station_id}` to retrieve the current `Station_Metric_Snapshot` for the selected station. Both endpoints require a `Client_Credential` and are HTTPS-only.

The displayed card follows the public wait-time card requirements and the Opus UI guidelines: station name, a large estimated wait time rounded to whole minutes, a queue status using the Opus status color system, open/active lanes, a last-updated timestamp, and a "Powered by Opus LaneSight" attribution. The presentation is deliberately simple and non-technical and does not expose internal model jargon such as confidence scores or raw field names.

The page must visibly handle the interaction states defined in the UI guidelines: loading, empty (no stations or no data), low-confidence (public estimate withheld or flagged), and error (API unreachable).

Because the site is a public static asset and the Station Statistics API requires a credential, this document captures how the demo supplies the `Client_Credential` for demo purposes and explicitly flags that embedding a credential in a public static site is a known constraint that is not production-safe.

## Glossary

- **Public_Dashboard**: The static demo website hosted on Amazon S3 static website hosting that displays public wait-time information for a selected station.
- **Station_Stats_API**: The existing AWS-hosted HTTP service (defined in the `station-stats-api` spec) that serves stored `Station_Metric_Snapshot` records; the `Public_Dashboard` reads from this service.
- **Station_List_Endpoint**: The `GET /stations` resource of the `Station_Stats_API` that returns the `Station_Identifier` and current `timestamp` of every station that has a stored snapshot.
- **Station_Metric_Endpoint**: The `GET /stations/{station_id}` resource of the `Station_Stats_API` that returns the current `Station_Metric_Snapshot` for one station.
- **Station_Metric_Snapshot**: The station-level statistics record returned by the `Station_Metric_Endpoint`, containing the fields station_id, timestamp, vehicles_in_queue, vehicles_in_bay, active_lanes, average_queue_wait_minutes, average_inspection_minutes, estimated_public_wait_minutes, throughput_per_hour, slowest_lane_id, and confidence_score.
- **Station_Identifier**: The string identifying an inspection station, carried in the snapshot's station_id field.
- **Station_Selector**: The dropdown control on the `Public_Dashboard` that lists the stations available from the `Station_List_Endpoint` and from which the viewer chooses one station.
- **Public_Wait_Card**: The motorist-facing card on the `Public_Dashboard` that displays a selected station's wait-time information.
- **Client_Credential**: The API key or token the `Public_Dashboard` presents to the `Station_Stats_API` to authenticate its read requests.
- **Demo_Config**: The demo-only configuration value supplied to the `Public_Dashboard` at load time that provides the `Station_Stats_API` base URL and the `Client_Credential`.
- **Queue_Status**: The motorist-facing status label and color derived from the Opus status color system, one of "Normal wait" (green), "Moderate wait" (blue), "Queue building" (orange), or "Data unavailable" (gray).
- **Confidence_Threshold**: The minimum confidence_score value at or above which the `Public_Dashboard` displays a public estimate, set to 0.5 for this demo.
- **Estimated_Wait_Display**: The large wait-time value shown on the `Public_Wait_Card`, derived from estimated_public_wait_minutes and rounded to whole minutes.

## Requirements

### Requirement 1: Host the demo as an S3 static website

**User Story:** As a hackathon presenter, I want the public wait-time page served as a static website from Amazon S3, so that I can demonstrate the motorist experience without running a server.

#### Acceptance Criteria

1. THE Public_Dashboard SHALL consist only of static assets (HTML, CSS, JavaScript, and static images) served through Amazon S3 static website hosting.
2. WHEN a viewer requests the site root, THE Public_Dashboard SHALL serve a single-page wait-time page as the index document and SHALL render its initial layout within 3 seconds over a connection of at least 5 Mbps.
3. THE Public_Dashboard SHALL operate entirely in the viewer's browser and SHALL NOT depend on any server-side application code other than the Station_Stats_API.
4. THE Public_Dashboard SHALL retrieve all station data exclusively from the Station_Stats_API over HTTPS, and SHALL NOT issue station data requests over any non-HTTPS scheme.
5. WHEN the Public_Dashboard requests station data from the Station_Stats_API, THE Public_Dashboard SHALL apply a request timeout of 10 seconds.

### Requirement 2: Provide demo configuration and credential

**User Story:** As a hackathon presenter, I want the site to know the API location and credential at load time, so that the demo can call the Station Statistics API without manual setup.

#### Acceptance Criteria

1. WHEN the Public_Dashboard loads, THE Public_Dashboard SHALL read the Station_Stats_API base URL and the Client_Credential from the Demo_Config before issuing any request to the Station_Stats_API.
2. WHEN the Public_Dashboard sends a request to the Station_List_Endpoint or the Station_Metric_Endpoint, THE Public_Dashboard SHALL include the Client_Credential from the Demo_Config.
3. WHEN the Public_Dashboard sends a request to the Station_List_Endpoint or the Station_Metric_Endpoint, THE Public_Dashboard SHALL send the request over HTTPS.
4. IF the Demo_Config does not provide both a non-empty Station_Stats_API base URL and a non-empty Client_Credential, THEN THE Public_Dashboard SHALL display an error state indicating the demo is not configured and SHALL NOT attempt any request to the Station_Stats_API.
5. IF the configured Station_Stats_API base URL does not use the HTTPS scheme, THEN THE Public_Dashboard SHALL display the not-configured error state and SHALL NOT attempt any request to the Station_Stats_API.
6. THE Public_Dashboard SHALL exclude the Client_Credential value from all viewer-visible output, including on-screen text, displayed URLs, and visible request parameters.
7. THE Demo_Config SHALL be documented as a demo-only mechanism, and the design SHALL record that embedding a Client_Credential in a publicly hosted static site exposes the credential to any visitor and is not safe for production use.

### Requirement 3: Populate the station selector

**User Story:** As a motorist viewing the demo, I want to choose a station from a list, so that I can see the wait time for the station I care about.

#### Acceptance Criteria

1. WHEN the Public_Dashboard finishes loading, THE Public_Dashboard SHALL request the list of stations from the Station_List_Endpoint within 1 second of load completion.
2. WHEN the Station_List_Endpoint returns a non-empty list of 1 to 500 stations, THE Public_Dashboard SHALL populate the Station_Selector with exactly one option per unique returned Station_Identifier, preserving the returned order.
3. IF the Station_List_Endpoint returns duplicate Station_Identifiers, THEN THE Public_Dashboard SHALL retain the first occurrence and discard the duplicates.
4. WHILE the Public_Dashboard is awaiting the response from the Station_List_Endpoint, THE Public_Dashboard SHALL display a loading state for the Station_Selector within 200 milliseconds and SHALL disable selector input until the response is handled.
5. IF the Station_List_Endpoint returns an empty list, THEN THE Public_Dashboard SHALL display an empty state indicating that no stations are currently publishing wait-time data and SHALL leave the Station_Selector with no selectable options.
6. IF the request to the Station_List_Endpoint fails due to a network error, a 10-second timeout, or an HTTP 4xx or 5xx response, THEN THE Public_Dashboard SHALL replace the loading state with an error state indicating that station data is currently unavailable.

### Requirement 4: Retrieve and display a selected station's stats

**User Story:** As a motorist viewing the demo, I want the page to show the current wait information when I pick a station, so that I get an up-to-date estimate.

#### Acceptance Criteria

1. WHEN the viewer selects a Station_Identifier in the Station_Selector, THE Public_Dashboard SHALL request the current Station_Metric_Snapshot for that Station_Identifier from the Station_Metric_Endpoint within 200 milliseconds of the selection.
2. WHILE the Public_Dashboard is awaiting the response from the Station_Metric_Endpoint, THE Public_Dashboard SHALL display a loading state for the Public_Wait_Card.
3. WHEN the Station_Metric_Endpoint returns a Station_Metric_Snapshot with HTTP status 200, THE Public_Dashboard SHALL display on the Public_Wait_Card the station name, the Estimated_Wait_Display, the Queue_Status, the open-lane count, and the last-updated timestamp for that station.
4. WHEN the viewer changes the selected Station_Identifier, THE Public_Dashboard SHALL replace the Public_Wait_Card contents with the newly selected station's information and SHALL clear any prior loading, empty, or error state for the card.
5. IF the Station_Metric_Endpoint returns HTTP status 404 for the selected Station_Identifier, THEN THE Public_Dashboard SHALL display an empty state indicating that no current wait-time data is available for that station and SHALL retain the selected Station_Identifier.
6. IF the request to the Station_Metric_Endpoint fails due to a network error, a 10-second timeout, an HTTP 4xx response other than 404, or an HTTP 5xx response, THEN THE Public_Dashboard SHALL display an error state indicating that wait-time data is currently unavailable and SHALL retain the selected Station_Identifier.

### Requirement 5: Present the public wait-time card

**User Story:** As a motorist, I want a clear and simple wait-time card, so that I can understand the wait without technical detail.

#### Acceptance Criteria

1. WHEN the Public_Dashboard displays the Public_Wait_Card for a station, THE Public_Wait_Card SHALL display the station name, the Estimated_Wait_Display, the Queue_Status, the open lanes, the last-updated timestamp, and the text "Powered by Opus LaneSight".
2. WHEN the Public_Dashboard computes the Estimated_Wait_Display, THE Public_Dashboard SHALL round the estimated_public_wait_minutes value to the nearest whole minute with halves rounded up, displaying a non-negative integer with no decimal places and a minutes label.
3. WHEN the Public_Dashboard displays the open lanes, THE Public_Wait_Card SHALL show the active_lanes value as a whole-number count of open lanes.
4. WHEN the Public_Dashboard displays the last-updated timestamp, THE Public_Wait_Card SHALL render the snapshot timestamp value as a 12-hour local clock time with an AM/PM indicator, without a date, seconds, or UTC offset.
5. THE Public_Wait_Card SHALL exclude the field names, the confidence_score value, the slowest_lane_id value, the average_inspection_minutes value, the average_queue_wait_minutes value, the throughput_per_hour value, and the vehicles_in_bay value from the motorist-facing display.

### Requirement 6: Derive queue status from the status color system

**User Story:** As a motorist, I want an at-a-glance status indicator, so that I can quickly judge whether the station is busy.

#### Acceptance Criteria

1. WHEN a numeric estimated_public_wait_minutes value is available and that value, rounded to the nearest whole minute with halves rounded up, is in the range 0 to 10 inclusive, THE Public_Dashboard SHALL set the Queue_Status to "Normal wait" using the Opus green status color (#93D500).
2. WHEN a numeric estimated_public_wait_minutes value is available and that value, rounded to the nearest whole minute with halves rounded up, is greater than 10 and at most 25, THE Public_Dashboard SHALL set the Queue_Status to "Moderate wait" using the Opus blue status color (#00A0E0).
3. WHEN a numeric estimated_public_wait_minutes value is available and that value, rounded to the nearest whole minute with halves rounded up, is greater than 25, THE Public_Dashboard SHALL set the Queue_Status to "Queue building" using the Opus orange status color (#FF8200).
4. IF the estimated_public_wait_minutes value is unavailable, null, or cannot be determined, THEN THE Public_Dashboard SHALL set the Queue_Status to "Data unavailable" using the Opus gray status color (#54565A).
5. THE Public_Wait_Card SHALL display the Queue_Status as a visible text label paired with its status color, and SHALL NOT communicate status through color alone.

### Requirement 7: Withhold low-confidence estimates

**User Story:** As an Opus stakeholder, I want low-confidence estimates withheld from the public, so that the demo does not present unreliable wait times as fact.

#### Acceptance Criteria

1. IF the confidence_score of the selected station's Station_Metric_Snapshot is below the Confidence_Threshold of 0.5, THEN THE Public_Dashboard SHALL display a low-confidence state on the Public_Wait_Card and SHALL withhold the Estimated_Wait_Display so that no numeric wait time is rendered.
2. WHILE the Public_Wait_Card is in the low-confidence state, THE Public_Dashboard SHALL set the Queue_Status to "Data unavailable" using the Opus gray status color (#54565A) paired with a visible text label.
3. WHILE the Public_Wait_Card is in the low-confidence state, THE Public_Dashboard SHALL display non-technical text indicating that a wait-time estimate is temporarily unavailable, without showing any internal metric, score, or model jargon.
4. WHEN the confidence_score of the selected station's Station_Metric_Snapshot is at or above the Confidence_Threshold of 0.5, THE Public_Dashboard SHALL display the Estimated_Wait_Display and the Queue_Status derived from the estimated wait.
5. IF the selected station's Station_Metric_Snapshot is missing the confidence_score, THEN THE Public_Dashboard SHALL treat the snapshot as low-confidence and apply the low-confidence state.

### Requirement 8: Follow the Opus UI guidelines

**User Story:** As an Opus brand stakeholder, I want the demo to follow Opus visual standards, so that it looks like a credible Opus product.

#### Acceptance Criteria

1. THE Public_Dashboard SHALL render text using the Roboto font family with an Arial, Helvetica, then generic sans-serif fallback.
2. THE Public_Dashboard SHALL use the Opus color palette defined in the Opus UI guidelines for all interface colors.
3. THE Public_Dashboard SHALL restrict the Opus orange color to attention and warning states only.
4. THE Public_Dashboard SHALL display all headings in sentence case, capitalizing only the first word and proper nouns, with no all-caps headings.
5. THE Public_Dashboard SHALL present a gradient hero area using the Opus brand gradient defined in the Opus UI guidelines.
6. THE Public_Dashboard SHALL style the Public_Wait_Card using the Opus card style defined in the Opus UI guidelines.
7. THE Public_Dashboard SHALL maintain a text contrast ratio of at least 4.5:1 for body text and at least 3:1 for large text against its backgrounds.
8. THE Public_Dashboard SHALL pair every status color with a visible text label so that status is not communicated by color alone.

### Requirement 9: Handle interaction states

**User Story:** As a motorist viewing the demo, I want clear feedback in every situation, so that I am never left looking at a blank or confusing screen.

#### Acceptance Criteria

1. WHILE the Public_Dashboard is awaiting any response from the Station_Stats_API, THE Public_Dashboard SHALL display a loading state within 500 milliseconds of the request start, showing no numeric wait-time value and no internal model, detection, or error terminology.
2. IF no stations are available, or the selected station has no current data, THEN THE Public_Dashboard SHALL display an empty state that omits any numeric wait-time value and explains that wait-time data will appear when station activity resumes.
3. IF a request to the Station_Stats_API cannot be completed due to a connection failure or a 10-second timeout, THEN THE Public_Dashboard SHALL display an error state indicating that the service is currently unavailable and SHALL retain that error state until a later request succeeds.
4. WHEN the selected station's Station_Metric_Snapshot indicates low confidence, THE Public_Dashboard SHALL display the low-confidence state with the Estimated_Wait_Display withheld.
5. WHEN the Public_Dashboard transitions between the loading, empty, low-confidence, error, and populated states, THE Public_Dashboard SHALL display exactly one of these states for the Public_Wait_Card at a time.
