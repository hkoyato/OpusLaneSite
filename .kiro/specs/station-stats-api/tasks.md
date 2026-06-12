# Implementation Plan: Station Statistics API

## Overview

This plan implements the Station Statistics API as Python code: a cloud ingestion/retrieval
service (validation, last-write-wins storage, snapshot + metrics handlers, API Gateway wiring,
logging) and the client-side `LaneSight_Client` (bounded buffer, exponential backoff,
submission/retry/eviction/duplicate handling, and the `Connectivity_Notification` GUI surface).

The pure-logic seams (validator, `StatisticsStore` against an in-memory fake, `PendingSnapshotBuffer`,
backoff function, client outcome handler, notification reducer, log builder) are verified with
Hypothesis property-based tests for Properties 1–20. The workspace already uses Hypothesis
(`.hypothesis/`); reuse it rather than building a PBT harness from scratch. Each property test is
tagged with a comment of the form `# Feature: station-stats-api, Property N: <text>` and runs with
`@settings(max_examples=100)` or higher. Infrastructure behavior (HTTPS-only, credential auth,
method routing, latency, TLS) is covered by integration, smoke, and UI tests.

Tasks build incrementally: shared types and pure logic first, then handlers, then gateway wiring,
then the client and GUI, then end-to-end integration. Each step wires into prior steps so no code
is left orphaned.

## Tasks

- [x] 1. Set up project structure and shared types
  - [x] 1.1 Create package layout and shared HTTP result types
    - Create `station_stats_api/` and `lanesight_client/` packages and a `tests/` directory
    - Define `HttpResult` (status code + JSON-serializable body) and shared status-mapping constants
    - Add Hypothesis to the test config and confirm the existing `.hypothesis/` cache is used
    - _Requirements: 1.2, 1.4_

- [x] 2. Implement snapshot validation
  - [x] 2.1 Implement UTC timestamp normalization
    - Parse ISO 8601 with explicit offset or `Z`; reject naive/invalid strings
    - Produce a comparable UTC instant while preserving the original submitted string
    - _Requirements: 4.2, 1.3, 5.3_

  - [x] 2.2 Implement `ValidationResult` and `validate_snapshot`
    - Enforce field constraints from the data model: `station_id` 1–64 `[a-z0-9_-]`; ISO 8601 timestamp; four integer fields in `[0, 1000000]`; three minute fields in `[0, 100000]`; `confidence_score` in `[0, 1]`; `slowest_lane_id` null or 1–64 `[a-z0-9_-]`
    - Treat any Glossary field other than `slowest_lane_id` as required and non-null
    - Return `failing_fields` listing exactly the violating fields; populate `cleaned` (Glossary fields only) iff valid
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 2.8, 5.5_

  - [x] 2.3 Write property test for validation acceptance
    - **Property 3: Validation accepts exactly the well-formed snapshots**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.8, 5.5**
    - Generators produce valid snapshots, boundary values (0, 1, 1000000, 100000, 1.0), and mixed offset/`Z` timestamps denoting the same instant

  - [x] 2.4 Write property test for rejection field-naming
    - **Property 4: Rejected snapshots name exactly the failing fields and store nothing**
    - **Validates: Requirements 2.6**
    - Generate parsable snapshots with a known set of violated fields (including missing/null required fields) and assert `failing_fields` equals that set

- [x] 3. Implement the Statistics_Store adapter
  - [x] 3.1 Define `StatisticsStore` protocol and `PutOutcome`
    - Declare `put_if_newer`, `get`, `list_index` and the `STORED | DUPLICATE | RETAINED_EXISTING` outcome enum
    - Document the HTTP mapping: `STORED → 201`, `DUPLICATE → 200`, `RETAINED_EXISTING → 201`
    - _Requirements: 4.1, 4.2_

  - [x] 3.2 Implement in-memory `StatisticsStore` fake with `put_if_newer`
    - Last-write-wins by UTC-normalized timestamp; equal `(station_id, timestamp)` → DUPLICATE; earlier-or-equal-but-different → RETAINED_EXISTING
    - Index one current snapshot per `station_id`; implement `get` and `list_index` projection of `(station_id, timestamp)`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.4, 8.8_

  - [x] 3.3 Write property test for latest-instant convergence
    - **Property 6: The current snapshot is the latest instant, regardless of order**
    - **Validates: Requirements 4.2, 4.3, 4.6**

  - [x] 3.4 Write property test for per-station independence
    - **Property 7: Stations are retained independently**
    - **Validates: Requirements 4.4, 4.5, 6.4**
    - Include collections at and above the Supported_Station_Count of 50 distinct stations

  - [x] 3.5 Write property test for idempotent resubmission
    - **Property 10: Resubmitting a stored snapshot is idempotent**
    - **Validates: Requirements 8.8**

  - [x] 3.6 Implement DynamoDB-backed `StatisticsStore`
    - Conditional `PutItem` with `attribute_not_exists(station_id) OR :new_utc > timestamp_utc`; map condition-check failures to DUPLICATE vs RETAINED_EXISTING; on-demand billing; list projection of `station_id`, `timestamp`
    - Store `station_id`, `timestamp` (as submitted), `timestamp_utc`, and the `snapshot` map
    - _Requirements: 4.1, 4.2, 4.3, 4.6, 6.3, 10.2_

- [x] 4. Implement the Snapshot (POST) handler
  - [x] 4.1 Implement `handle_snapshot`
    - Parse body as JSON (`400` malformed-JSON on failure); validate (`422` naming each failing field); strip extra fields; call `put_if_newer`; map outcomes to `201`/`200`; storage error → `503` generic; never raise for client error
    - _Requirements: 1.2, 1.4, 2.5, 2.6, 2.7, 8.8, 10.2_

  - [x] 4.2 Write property test for accept-and-store
    - **Property 1: Valid snapshots are accepted and stored**
    - **Validates: Requirements 1.2, 1.4**

  - [x] 4.3 Write property test for extra-field stripping
    - **Property 5: Extra fields are stripped and do not affect acceptance**
    - **Validates: Requirements 2.7**

  - [x] 4.4 Write property test for generic 5xx bodies
    - **Property 20: 5xx responses are generic**
    - **Validates: Requirements 10.4**
    - Inject storage faults and assert the body has no stack traces, internal codes, or implementation details

  - [x] 4.5 Write unit tests for malformed-JSON and oversize bodies
    - Unparseable body → `400`; body > 16KB → `413` with max-body-size message and nothing stored
    - _Requirements: 2.5, 1.6_

- [x] 5. Implement the Metrics (GET) handler
  - [x] 5.1 Implement `get_station` and `list_stations`
    - Single read: validate `station_id` format (`400` if malformed), return `200` snapshot or `404` if absent
    - List read: return `200` with `{station_id, timestamp}` for every stored station; empty list when none
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 5.6_

  - [x] 5.2 Write property test for storage round-trip
    - **Property 2: Storage and retrieval preserve every field**
    - **Validates: Requirements 1.3, 4.1, 5.1, 5.3**

  - [x] 5.3 Write property test for the list endpoint
    - **Property 8: The list endpoint reflects exactly the stored stations**
    - **Validates: Requirements 5.4, 5.6**

  - [x] 5.4 Write property test for unknown-station lookups
    - **Property 9: Unknown well-formed stations return 404**
    - **Validates: Requirements 5.2**

  - [x] 5.5 Write unit tests for empty-store list and malformed GET id
    - Empty store list → `200` with `[]`; malformed `station_id` on GET → `400`
    - _Requirements: 5.6, 5.5_

- [x] 6. Implement logging and observability
  - [x] 6.1 Implement the guarded log-entry builder
    - Emit exactly one entry per handled request recording `station_id` (or explicit absent/unparseable indicator), HTTP status, request timestamp (ISO 8601), and a rejection category for rejects
    - Redact `Client_Credential` and any plate/driver-identifying data; wrap emit so logging failure never fails the request
    - _Requirements: 10.1, 3.5, 10.3, 10.5_

  - [x] 6.2 Write property test for log/response hygiene
    - **Property 18: Logs and responses never leak credentials or driver data**
    - **Validates: Requirements 3.5, 10.3**
    - Generate credential- and plate-like strings and assert they never appear in log entries or response bodies

  - [x] 6.3 Write property test for one-complete-log-entry-per-request
    - **Property 19: Every handled request produces one complete log entry**
    - **Validates: Requirements 10.1**

  - [x] 6.4 Write unit test for logging-failure resilience
    - When the log emit raises, the request still returns its intended status
    - _Requirements: 10.5_

- [x] 7. Checkpoint - server-side logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Wire the API Gateway and Lambda entry points
  - [x] 8.1 Define API Gateway resources, methods, and policies (IaC)
    - POST `/stations/{station_id}/snapshot`, GET `/stations/{station_id}`, GET `/stations`; credential authorizer (`401` missing, `403` unknown/revoked); HTTPS-only custom domain; 16KB request size limit (`413`); non-matching method → `405`
    - _Requirements: 1.1, 1.5, 1.6, 3.1, 3.2, 3.3, 3.4, 3.6, 5.7_

  - [x] 8.2 Implement the Lambda event adapter wiring handlers to the gateway
    - Translate API Gateway proxy events into `handle_snapshot` / `get_station` / `list_stations` calls and `HttpResult` back into proxy responses; inject the DynamoDB `StatisticsStore` and log builder; map unexpected faults to `500` generic
    - _Requirements: 1.2, 5.1, 5.4, 10.4_

- [x] 9. Implement client models and the Pending_Snapshot_Buffer
  - [x] 9.1 Implement client data models
    - `Snapshot`, `ClientConfig` (credential never logged), and the `SubmitOutcome` enum (`PUBLISHED`/`DUPLICATE`/`DISCARDED`/`RETRY`)
    - _Requirements: 7.1, 7.2_

  - [x] 9.2 Implement `PendingSnapshotBuffer`
    - Bounded FIFO ordered by ascending timestamp, capacity 1000; on add at capacity evict and return the single earliest-timestamp snapshot; `peek_oldest`, `remove`, `__len__`
    - _Requirements: 8.4, 8.5_

  - [x] 9.3 Write property test for the bounded buffer
    - **Property 12: The pending buffer is bounded and evicts the oldest**
    - **Validates: Requirements 8.4**

- [x] 10. Implement the backoff scheduler
  - [x] 10.1 Implement `_next_backoff`
    - `delay = min(2 * 2^(n-1), 60)` seconds for the n-th consecutive failure; reset on success
    - _Requirements: 8.2_

  - [x] 10.2 Write property test for exponential backoff
    - **Property 14: Exponential backoff doubles from 2s and caps at 60s**
    - **Validates: Requirements 8.2**

  - [x] 10.3 Write unit test for concrete backoff values
    - Assert the sequence 2, 4, 8, 16, 32, 60, 60 and that no fixed max-attempt cap exists
    - _Requirements: 8.2, 8.3_

- [x] 11. Implement the LaneSight_Client submission and retry logic
  - [x] 11.1 Implement enqueue, configuration check, and submission
    - `on_snapshot_produced` enqueues and stamps `station_id` with the active `Station_Identifier`; if `API_Base_URL` or `Client_Credential` is unconfigured, skip the attempt, drop the snapshot, and surface a not-configured notification within 2s; otherwise submit JSON over HTTPS with a 10s timeout presenting the credential
    - _Requirements: 7.1, 7.2, 7.5, 7.6, 7.7_

  - [x] 11.2 Implement outcome handling, drain ordering, and retry scheduling
    - `201`/duplicate `200` → remove + reset backoff + clear notice; `400`/`422` → discard + log reason; timeout/network/`5xx`/`401`/`403` → retain + schedule backoff retry; drain oldest-first, stop the pass on first failure and resume after the next backoff interval
    - _Requirements: 7.3, 7.4, 8.1, 8.3, 8.5, 8.6, 8.7_

  - [x] 11.3 Write property test for per-response buffer handling
    - **Property 11: Buffer outcome handling is correct per response**
    - **Validates: Requirements 7.3, 7.4, 8.1, 8.6**

  - [x] 11.4 Write property test for drain ordering
    - **Property 13: Draining publishes in ascending timestamp order and preserves order on failure**
    - **Validates: Requirements 8.5, 8.7**

  - [x] 11.5 Write property test for unconfigured-client behavior
    - **Property 15: Unconfigured client skips submission and reports not-configured**
    - **Validates: Requirements 7.6**

  - [x] 11.6 Write property test for station-id stamping
    - **Property 16: Submitted snapshots carry the active station identifier**
    - **Validates: Requirements 7.1, 7.2, 7.7**

  - [x] 11.7 Write unit test for timeout and no-max-attempts configuration
    - Assert the 10s submission timeout is configured and no fixed attempt cap is imposed
    - _Requirements: 7.5, 8.3_

- [x] 12. Checkpoint - client submission and retry
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement the Connectivity_Notification
  - [x] 13.1 Implement the notification state reducer
    - Derive state from the latest outcome and live buffer count: auth category on `401`/`403`; outage category on timeout/network/`5xx`; permanent-drop on eviction; cleared (resumed) after success; display the current `Pending_Snapshot_Buffer` count while visible
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.7_

  - [x] 13.2 Write property test for notification state derivation
    - **Property 17: Notification state derives from the latest outcome and buffer**
    - **Validates: Requirements 9.1, 9.2, 9.5, 9.7**

  - [x] 13.3 Implement the GUI Connectivity_Notification surface
    - Bind the surface to client state; render the warning treatment using the Opus orange token (`#FF8200`) paired with a visible text label (never color alone); show buffer count; keep other views interactive
    - _Requirements: 9.4, 9.6_

  - [x] 13.4 Write UI tests for the notification surface
    - Appears within 2s on failure and clears within 2s on recovery; count updates within 2s; auth copy distinct from outage copy; permanent-drop indication on eviction; orange `#FF8200` paired with text label; other views remain interactive
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [x] 14. Integration, smoke, and load tests
  - [x] 14.1 Write integration tests for credential enforcement
    - Missing credential → `401`, bad/revoked → `403` on both endpoints, nothing stored/returned
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 14.2 Write integration tests for method routing
    - Non-POST on snapshot resource → `405`; non-GET on metrics resource → `405`
    - _Requirements: 1.5, 5.7_

  - [x] 14.3 Write integration test for HTTPS-only enforcement
    - Unencrypted request rejected before the handler; nothing stored/returned
    - _Requirements: 3.4, 3.6_

  - [x] 14.4 Write integration test for storage-error handling
    - Injected storage error → `503` with no partial record
    - _Requirements: 10.2_

  - [x] 14.5 Write integration test for cross-station independence
    - A failing request for one station does not block storage for another
    - _Requirements: 6.4_

  - [x] 14.6 Write load tests for scale and latency
    - 50 stations submitting within 60s succeed; p95 ≤ 2000ms under concurrent load; 100 stations still return `201` with no schema change
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 14.7 Write smoke tests for routing and TLS policy
    - POST accepts a ≤16KB body; custom domain enforces HTTPS-only
    - _Requirements: 1.1, 3.4_

- [x] 15. Final checkpoint - full suite
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Property tests use Hypothesis with `@settings(max_examples=100)` (or higher) and are tagged `# Feature: station-stats-api, Property N: <text>`. They target pure-logic seams against in-memory fakes so 100+ iterations stay cheap.
- Properties 1–20 each map to exactly one property-based test; infrastructure behavior is covered by integration, smoke, and load tests rather than property tests.
- Each task references specific requirement clauses for traceability; checkpoints provide incremental validation breaks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "9.1", "10.1"] },
    { "id": 1, "tasks": ["2.2", "3.1", "6.1", "9.2", "10.2", "10.3", "13.1"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.2", "3.6", "6.2", "6.3", "6.4", "9.3", "11.1", "13.2", "13.3"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "4.1", "5.1", "11.2", "13.4", "8.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "5.2", "5.3", "5.4", "5.5", "11.3", "11.4", "11.5", "11.6", "11.7", "8.2"] },
    { "id": 5, "tasks": ["14.1", "14.2", "14.3", "14.4", "14.5", "14.6", "14.7"] }
  ]
}
```
