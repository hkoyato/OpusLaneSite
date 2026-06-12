# Requirements Document

## Introduction

The Station Statistics API is an AWS-hosted ingestion service that collects station wait-time statistics from every Opus LaneSight instance running in the field. Today each LaneSight instance produces Station Metric Snapshots locally and surfaces them only in its own GUI, dashboard, and reports. There is no central place to collect snapshots across stations, so program operations teams cannot see all stations together and public-facing consumers cannot retrieve a station's current wait time from a shared source.

This feature introduces a cloud endpoint that LaneSight instances call to publish their current statistics, a stored record of the most recent statistics per station, and a read endpoint that internal and public consumers use to retrieve them. The service is sized for an initial deployment of up to 50 stations and is designed to scale beyond that without redesign. On the client side, this feature defines how the LaneSight application submits snapshots and, critically, how it notifies the operator in the GUI when the application cannot reach the service so that operators are never left believing data is being published when it is not.

This document covers the ingestion endpoint, payload validation, authentication, storage, retrieval, client submission behavior, and the GUI connectivity notification. It does not define the visual styling of the internal dashboard or public wait-time card, the computer-vision pipeline that produces snapshots, or the Bedrock summary generation. The structure of the Station Metric Snapshot is treated as a given input from the existing data model.

## Glossary

- **Station_Stats_API**: The AWS-hosted HTTP service, fronted by API Gateway and backed by AWS Lambda and DynamoDB, that ingests, stores, and serves station wait-time statistics.
- **Snapshot_Endpoint**: The HTTP POST endpoint of the Station_Stats_API that receives a single Station_Metric_Snapshot for one station.
- **Metrics_Query_Endpoint**: The HTTP GET endpoint of the Station_Stats_API that returns the most recent stored Station_Metric_Snapshot for a requested station.
- **Statistics_Store**: The DynamoDB-backed persistence layer that stores Station_Metric_Snapshots keyed by Station_Identifier.
- **Station_Metric_Snapshot**: The aggregated station-level statistics record submitted by a LaneSight instance, containing the fields station_id, timestamp, vehicles_in_queue, vehicles_in_bay, active_lanes, average_queue_wait_minutes, average_inspection_minutes, estimated_public_wait_minutes, throughput_per_hour, slowest_lane_id, and confidence_score.
- **Station_Identifier**: The operator-configured string identifying which inspection station a snapshot belongs to, carried in the snapshot's station_id field, as defined by the station-identification spec.
- **Client_Credential**: The API key or signed token that a LaneSight instance presents to authenticate requests to the Station_Stats_API.
- **LaneSight_Client**: The component within the GUI_Application that serializes Station_Metric_Snapshots and submits them to the Snapshot_Endpoint.
- **GUI_Application**: The Opus LaneSight desktop application that runs the detection pipeline and hosts the LaneSight_Client, as defined by the lanesight-gui spec.
- **API_Base_URL**: The configured base URL of the Station_Stats_API that the LaneSight_Client targets.
- **Connectivity_Notification**: The visible message the GUI_Application displays to the operator when the LaneSight_Client cannot successfully publish to the Station_Stats_API.
- **Submission_Attempt**: A single HTTP request made by the LaneSight_Client to the Snapshot_Endpoint for one Station_Metric_Snapshot.
- **Pending_Snapshot_Buffer**: The bounded in-memory queue in which the LaneSight_Client holds snapshots that have not yet been successfully published.
- **Supported_Station_Count**: The number of distinct stations the Station_Stats_API is required to serve concurrently, set to 50 for the initial deployment.

## Requirements

### Requirement 1: Ingest a station metric snapshot

**User Story:** As a program operations team, I want each LaneSight instance to publish its current statistics to a central service, so that all stations' wait-time data is collected in one place.

#### Acceptance Criteria

1. THE Snapshot_Endpoint SHALL accept HTTP POST requests whose body is a single JSON-encoded Station_Metric_Snapshot of at most 16 kilobytes in size.
2. WHEN the Snapshot_Endpoint receives a request containing a valid, authenticated Station_Metric_Snapshot, THE Station_Stats_API SHALL store the snapshot in the Statistics_Store and, only after the snapshot has been durably written, respond with HTTP status 201.
3. WHEN the Station_Stats_API stores a Station_Metric_Snapshot that has passed the validation rules in Requirement 2, THE Station_Stats_API SHALL preserve the values of station_id, timestamp, vehicles_in_queue, vehicles_in_bay, active_lanes, average_queue_wait_minutes, average_inspection_minutes, estimated_public_wait_minutes, throughput_per_hour, slowest_lane_id, and confidence_score exactly as submitted.
4. WHEN the Snapshot_Endpoint accepts a Station_Metric_Snapshot, THE Station_Stats_API SHALL return a response body containing the Station_Identifier and the value of the timestamp field of the accepted snapshot as stored.
5. WHEN the Snapshot_Endpoint receives an authenticated request whose HTTP method is not POST for the snapshot resource, THE Station_Stats_API SHALL respond with HTTP status 405.
6. IF the Snapshot_Endpoint receives a POST request whose body exceeds 16 kilobytes, THEN THE Station_Stats_API SHALL respond with HTTP status 413, identify the request as exceeding the maximum allowed body size in the response body, and SHALL NOT store any snapshot.

### Requirement 2: Validate the submitted snapshot

**User Story:** As a program operations analyst, I want the service to reject malformed statistics, so that the stored data is consistent and usable by downstream consumers.

#### Acceptance Criteria

1. THE Station_Stats_API SHALL treat a Station_Metric_Snapshot as valid only WHEN station_id is a non-empty string of 1 to 64 characters containing only lowercase letters, digits, hyphens, and underscores, and timestamp is a valid ISO 8601 date-time value that includes an explicit UTC offset or the 'Z' designator.
2. THE Station_Stats_API SHALL treat a Station_Metric_Snapshot as valid only WHEN vehicles_in_queue, vehicles_in_bay, active_lanes, and throughput_per_hour are each integers greater than or equal to 0 and less than or equal to 1,000,000.
3. THE Station_Stats_API SHALL treat a Station_Metric_Snapshot as valid only WHEN average_queue_wait_minutes, average_inspection_minutes, and estimated_public_wait_minutes are each numbers greater than or equal to 0 and less than or equal to 100,000.
4. THE Station_Stats_API SHALL treat a Station_Metric_Snapshot as valid only WHEN confidence_score is a number greater than or equal to 0 and less than or equal to 1.
5. IF the Snapshot_Endpoint receives a request body that cannot be parsed as JSON, THEN THE Station_Stats_API SHALL respond with HTTP status 400 and a body identifying the request as malformed JSON, and SHALL NOT store any snapshot.
6. IF the Snapshot_Endpoint receives a parsable Station_Metric_Snapshot in which any Glossary-defined field other than slowest_lane_id is missing or null, or in which any field value violates the validation rules in this requirement, THEN THE Station_Stats_API SHALL respond with HTTP status 422, name each failing field in the response body, and SHALL NOT store the snapshot.
7. WHERE the submitted Station_Metric_Snapshot includes fields beyond those defined in the Glossary, THE Station_Stats_API SHALL store the snapshot without those additional fields and SHALL still respond with HTTP status 201.
8. THE Station_Stats_API SHALL treat a Station_Metric_Snapshot as valid only WHEN slowest_lane_id is either null or a string of 1 to 64 characters containing only lowercase letters, digits, hyphens, and underscores.

### Requirement 3: Authenticate and authorize submissions

**User Story:** As a security stakeholder, I want only authorized LaneSight instances to publish statistics, so that the stored data cannot be forged or polluted by unauthorized callers.

#### Acceptance Criteria

1. THE Station_Stats_API SHALL require a Client_Credential on every request to the Snapshot_Endpoint and the Metrics_Query_Endpoint.
2. IF a request to the Snapshot_Endpoint or the Metrics_Query_Endpoint omits a Client_Credential, THEN THE Station_Stats_API SHALL respond with HTTP status 401, SHALL NOT store any snapshot, and SHALL NOT return any stored snapshot.
3. IF a request to the Snapshot_Endpoint or the Metrics_Query_Endpoint presents a Client_Credential that is not recognized or has been revoked, THEN THE Station_Stats_API SHALL respond with HTTP status 403, SHALL NOT store any snapshot, and SHALL NOT return any stored snapshot.
4. THE Station_Stats_API SHALL accept requests only over HTTPS.
5. THE Station_Stats_API SHALL exclude the value of any Client_Credential from every log entry and every response body.
6. IF the Station_Stats_API receives a request over unencrypted HTTP, THEN THE Station_Stats_API SHALL reject the request without processing its body, SHALL NOT store any snapshot, and SHALL NOT return any stored snapshot.

### Requirement 4: Store the latest statistics per station

**User Story:** As a program operations team, I want the most recent statistics retained for each station, so that consumers always see each station's current wait time.

#### Acceptance Criteria

1. WHEN the Station_Stats_API stores a Station_Metric_Snapshot, THE Statistics_Store SHALL index that snapshot by its Station_Identifier such that the current snapshot for that Station_Identifier is retrievable through the Metrics_Query_Endpoint.
2. WHEN the Station_Stats_API stores a Station_Metric_Snapshot whose timestamp, compared as a UTC-normalized ISO 8601 date-time instant, is later than the timestamp of the currently stored snapshot for the same Station_Identifier, THE Statistics_Store SHALL make the newly stored snapshot the current snapshot for that Station_Identifier.
3. IF the Station_Stats_API stores a Station_Metric_Snapshot whose timestamp, compared as a UTC-normalized ISO 8601 date-time instant, is earlier than or equal to the timestamp of the currently stored snapshot for the same Station_Identifier, THEN THE Statistics_Store SHALL retain the existing current snapshot as the current snapshot for that Station_Identifier and SHALL NOT alter it.
4. THE Statistics_Store SHALL retain snapshots for distinct Station_Identifiers independently, such that storing a snapshot for one Station_Identifier does not alter the stored snapshot of any other Station_Identifier.
5. THE Statistics_Store SHALL concurrently retain a current snapshot for at least the Supported_Station_Count of distinct Station_Identifiers.
6. WHEN two or more Station_Metric_Snapshots for the same Station_Identifier are stored concurrently, THE Statistics_Store SHALL converge to a single current snapshot whose timestamp, compared as a UTC-normalized ISO 8601 date-time instant, is the latest among them.

### Requirement 5: Retrieve station statistics

**User Story:** As a developer building the internal dashboard and public wait-time card, I want to read a station's current statistics from the service, so that I can display up-to-date wait-time information.

#### Acceptance Criteria

1. WHEN the Metrics_Query_Endpoint receives an authenticated GET request for a Station_Identifier that has a stored current snapshot, THE Station_Stats_API SHALL respond with HTTP status 200 and a body containing that current Station_Metric_Snapshot.
2. IF the Metrics_Query_Endpoint receives an authenticated GET request for a well-formed Station_Identifier that has no stored snapshot, THEN THE Station_Stats_API SHALL respond with HTTP status 404 and a body indicating that no statistics exist for the requested station.
3. WHEN the Metrics_Query_Endpoint returns a Station_Metric_Snapshot, THE returned snapshot SHALL contain the same values for station_id, timestamp, vehicles_in_queue, vehicles_in_bay, active_lanes, average_queue_wait_minutes, average_inspection_minutes, estimated_public_wait_minutes, throughput_per_hour, slowest_lane_id, and confidence_score that were stored for that Station_Identifier.
4. WHEN the Metrics_Query_Endpoint receives an authenticated GET request without a Station_Identifier, THE Station_Stats_API SHALL respond with HTTP status 200 and a body listing the Station_Identifier and current timestamp of every station that has a stored snapshot.
5. IF the Metrics_Query_Endpoint receives an authenticated GET request for a Station_Identifier that does not conform to the station_id format rules defined in Requirement 2, THEN THE Station_Stats_API SHALL respond with HTTP status 400 and a body indicating that the requested Station_Identifier is malformed.
6. WHEN the Metrics_Query_Endpoint receives an authenticated GET request without a Station_Identifier and no station has a stored current snapshot, THE Station_Stats_API SHALL respond with HTTP status 200 and a body containing an empty list.
7. IF the Metrics_Query_Endpoint receives an authenticated request whose HTTP method is not GET for the metrics resource, THEN THE Station_Stats_API SHALL respond with HTTP status 405.

### Requirement 6: Scale to the supported station count

**User Story:** As a program operations team, I want the service to handle every deployed station and grow as more stations are added, so that adding stations does not require rebuilding the service.

#### Acceptance Criteria

1. THE Station_Stats_API SHALL accept and store valid snapshots for any number of distinct Station_Identifiers from 1 up to at least the Supported_Station_Count of 50, where each participating station submits at least one snapshot, within a single 60-second interval, without requiring 50 stations to be active.
2. WHILE snapshots are being submitted concurrently for up to the Supported_Station_Count of distinct stations, each submitting at least one snapshot per 60-second interval, THE Station_Stats_API SHALL respond to each accepted Snapshot_Endpoint request within 2000 milliseconds at the 95th percentile.
3. WHERE up to twice the Supported_Station_Count of distinct Station_Identifiers submit snapshots within a single 60-second interval, THE Station_Stats_API SHALL continue to accept and store valid snapshots, responding with HTTP status 201, without requiring a change to the Statistics_Store schema.
4. THE Station_Stats_API SHALL process each Submission_Attempt independently such that the failure, rejection, delay, or storage of one station's snapshot does not block the storage of another station's snapshot.

### Requirement 7: Submit snapshots from the LaneSight application

**User Story:** As a station operator, I want my LaneSight instance to publish its current statistics automatically, so that the central service reflects my station without manual steps.

#### Acceptance Criteria

1. WHEN the GUI_Application produces a Station_Metric_Snapshot, THE LaneSight_Client SHALL add that snapshot to the Pending_Snapshot_Buffer.
2. THE LaneSight_Client SHALL set the station_id field of each submitted Station_Metric_Snapshot to the active Station_Identifier of the GUI_Application at the time the snapshot is produced.
3. WHEN a Submission_Attempt receives an HTTP 201 response, THE LaneSight_Client SHALL treat that snapshot as successfully published and remove it from the Pending_Snapshot_Buffer.
4. WHEN a Submission_Attempt receives an HTTP 422 or HTTP 400 response, THE LaneSight_Client SHALL discard that snapshot from the Pending_Snapshot_Buffer and record the rejection reason in the application log.
5. THE LaneSight_Client SHALL apply a Submission_Attempt timeout of 10 seconds, after which an attempt that has not received a response is treated as failed.
6. IF the API_Base_URL or Client_Credential is not configured when a Station_Metric_Snapshot is produced, THEN THE LaneSight_Client SHALL skip the Submission_Attempt, remove that snapshot from the Pending_Snapshot_Buffer, and surface a Connectivity_Notification within 2 seconds indicating that statistics publishing is not configured.
7. WHERE both the API_Base_URL and Client_Credential are configured, WHEN a Station_Metric_Snapshot is added to the Pending_Snapshot_Buffer, THE LaneSight_Client SHALL make a Submission_Attempt that sends that snapshot as a JSON request body over HTTPS to the Snapshot_Endpoint at the API_Base_URL, presenting the configured Client_Credential.

### Requirement 8: Retry and buffer unpublished snapshots

**User Story:** As a station operator, I want statistics to be published reliably despite brief network problems, so that short outages do not cause permanent data loss.

#### Acceptance Criteria

1. IF a Submission_Attempt fails due to a timeout of 10 seconds, a network error, or an HTTP 5xx response, THEN THE LaneSight_Client SHALL retain the snapshot in the Pending_Snapshot_Buffer and schedule a retry.
2. THE LaneSight_Client SHALL retry a failed Submission_Attempt using exponential backoff that starts at 2 seconds and doubles after each consecutive failure, capped at 60 seconds between attempts.
3. THE LaneSight_Client SHALL continue retrying a failed snapshot until the snapshot is successfully published, discarded due to an HTTP 422 or HTTP 400 response, or evicted from the Pending_Snapshot_Buffer, without imposing a fixed maximum number of attempts.
4. WHEN the Pending_Snapshot_Buffer holds 1000 snapshots and a new snapshot is added, THE LaneSight_Client SHALL discard the single oldest snapshot, identified by the earliest timestamp, to make room.
5. WHEN a Submission_Attempt succeeds after one or more failed Submission_Attempts, THE LaneSight_Client SHALL publish the snapshots remaining in the Pending_Snapshot_Buffer in ascending chronological order of their timestamp, oldest first.
6. WHEN a Submission_Attempt for a snapshot succeeds, THE LaneSight_Client SHALL remove that snapshot from the Pending_Snapshot_Buffer.
7. IF a Submission_Attempt fails while the LaneSight_Client is publishing the snapshots remaining in the Pending_Snapshot_Buffer, THEN THE LaneSight_Client SHALL stop the current publishing pass, retain the remaining snapshots in chronological order, and resume publishing after the next backoff interval.
8. THE Snapshot_Endpoint SHALL treat a resubmitted Station_Metric_Snapshot that has the same Station_Identifier and timestamp as an already-stored snapshot as a duplicate and respond with HTTP status 200 without creating a conflicting record.

### Requirement 9: Notify the operator when the service is unreachable

**User Story:** As a station operator, I want a clear notification when my instance cannot reach the statistics service, so that I am never misled into thinking data is published when it is not.

#### Acceptance Criteria

1. IF a Submission_Attempt fails due to a timeout, a network error, an HTTP 5xx response, an HTTP 401 response, or an HTTP 403 response, THEN THE GUI_Application SHALL display a Connectivity_Notification within 2 seconds of the failed attempt indicating that statistics could not be published to the Station_Stats_API.
2. WHILE Submission_Attempts continue to fail, THE GUI_Application SHALL keep the Connectivity_Notification visible and SHALL update the displayed count of snapshots currently held in the Pending_Snapshot_Buffer within 2 seconds of a change to that count.
3. WHEN a Submission_Attempt succeeds after the Connectivity_Notification has been shown, THE GUI_Application SHALL clear the Connectivity_Notification within 2 seconds and indicate that statistics publishing has resumed.
4. THE Connectivity_Notification SHALL use the warning visual treatment defined by the Opus UI guidelines, pairing the orange attention color with a visible text label rather than relying on color alone.
5. IF a Submission_Attempt fails due to an HTTP 401 or HTTP 403 response, THEN THE Connectivity_Notification SHALL indicate that the failure is an authentication or authorization problem distinct from a network outage.
6. WHILE the Connectivity_Notification is displayed, THE GUI_Application SHALL allow the operator to interact with the detection pipeline view and any other view.
7. WHEN the LaneSight_Client discards the oldest snapshot from a full Pending_Snapshot_Buffer, THE GUI_Application SHALL indicate within 2 seconds through the Connectivity_Notification that unpublished snapshots are being permanently dropped.

### Requirement 10: Log and observe service activity

**User Story:** As an operations engineer, I want the service to record its activity and errors, so that I can monitor ingestion health and diagnose failures.

#### Acceptance Criteria

1. WHEN the Station_Stats_API accepts or rejects a Snapshot_Endpoint request, THE Station_Stats_API SHALL write a single log entry recording the Station_Identifier (or an explicit indicator when the Station_Identifier is absent or unparseable), the resulting HTTP status code, the request timestamp as an ISO 8601 date-time value, and, for a rejected request, a category describing the rejection reason.
2. IF the Statistics_Store cannot persist a valid, authenticated Station_Metric_Snapshot due to a storage error, THEN THE Station_Stats_API SHALL respond with HTTP status 503, SHALL write a log entry describing the storage failure, and SHALL NOT leave any partial record of that snapshot in the Statistics_Store.
3. THE Station_Stats_API SHALL exclude the contents of any Client_Credential and SHALL exclude any license plate text or driver-identifying data from every log entry.
4. WHEN the Station_Stats_API returns an HTTP 5xx response, THE response body SHALL contain a generic error message that indicates the request could not be completed and SHALL NOT contain internal stack traces, internal error codes, or implementation details.
5. IF the Station_Stats_API cannot write a log entry for a request, THEN THE Station_Stats_API SHALL continue to process that request and return the HTTP status it would otherwise return, without failing the request because of the logging error.
