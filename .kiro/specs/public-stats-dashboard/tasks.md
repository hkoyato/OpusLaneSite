# Implementation Plan: Public Stats Dashboard

## Overview

This plan converts the design into incremental coding steps for a static, single-page S3-hosted demo built with plain ES modules (no build step), tested with Vitest and fast-check. Work proceeds in dependency order: project scaffolding and the static page shell, then the pure presentation seams (each property-tested 1:1 against design Properties 1–13), then the Demo_Config loader and the network-touching API client, then the DOM view and the app controller that wires everything together, and finally the integration, snapshot, accessibility, and smoke tests. Each step builds on the previous ones and ends with integration so no code is left orphaned.

Implementation language: JavaScript (browser ES modules), per the design. Property-based tests use [fast-check](https://github.com/dubzzz/fast-check) on the [Vitest](https://vitest.dev/) runner, each running at least 100 examples and tagged `// Feature: public-stats-dashboard, Property {n}: {text}`.

## Tasks

- [x] 1. Set up project scaffolding and static page shell
  - [x] 1.1 Initialize the static project structure and test tooling
    - Create the deployable layout: `src/index.html` (index document), `src/styles.css`, `src/app.js` (controller entry), `src/config.example.js`, and an `src/lib/` folder for the pure ES modules (`config.js`, `apiClient.js`, `presentation.js`, `stateReducer.js`)
    - Add `package.json` with Vitest + fast-check as devDependencies (pinned versions), a `test` script using `vitest --run`, and `jsdom` as the Vitest environment for DOM tests
    - Add `vitest.config.js` configured for the jsdom environment and a `tests/` directory
    - Do NOT add a bundler or framework; modules stay as plain ES modules so they load directly from S3 and import directly into tests
    - _Requirements: 1.1, 1.3_

  - [x] 1.2 Build the static page shell and Opus visual treatment
    - Implement `index.html` with the page shell rendered synchronously: gradient hero (Opus brand gradient), product header ("Opus LaneSight"), the station selector control, and an initially empty wait-card region with stable containers for each card state
    - Implement `styles.css` using the Opus design tokens, Roboto font stack with Arial/Helvetica/sans-serif fallback, the Opus card style, sentence-case headings, and status color + left-border treatment; restrict orange to the attention state
    - Ensure the initial layout paints from static markup with no data dependency
    - _Requirements: 1.1, 1.2, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 2. Implement station de-duplication and wait rounding
  - [x] 2.1 Implement `dedupeStations` in `src/lib/presentation.js`
    - Keep the first occurrence of each `station_id` and preserve the returned first-seen order; discard later duplicates
    - _Requirements: 3.2, 3.3_

  - [x]* 2.2 Write property test for station de-duplication
    - **Property 1: Station de-duplication keeps first occurrence and preserves order**
    - **Validates: Requirements 3.2, 3.3**
    - Generate station lists (1–500 entries) with duplicates and varied order, plus empty lists; assert unique `station_id` values in first-seen order

  - [x] 2.3 Implement `roundWaitMinutes` in `src/lib/presentation.js`
    - Return `max(0, Math.floor(x + 0.5))` for finite numeric input; return `null` for `null`, `NaN`, or non-finite input
    - _Requirements: 5.2_

  - [x]* 2.4 Write property test for wait rounding
    - **Property 2: Wait rounding is round-half-up to a non-negative integer**
    - **Validates: Requirements 5.2**
    - Generate finite non-negative values (including halves like `x.5`) and `null`/`NaN`/non-finite inputs

- [x] 3. Implement queue-status derivation and timestamp formatting
  - [x] 3.1 Implement `deriveQueueStatus` in `src/lib/presentation.js`
    - Map rounded wait `r`: `0 ≤ r ≤ 10` → "Normal wait"/`#93D500`; `10 < r ≤ 25` → "Moderate wait"/`#00A0E0`; `r > 25` → "Queue building"/`#FF8200`; `null`/unavailable → "Data unavailable"/`#54565A`
    - Always return a non-empty label paired with the color
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.3, 8.8_

  - [x]* 3.2 Write property test for queue-status derivation
    - **Property 3: Queue status is correct across all ranges, always labelled, and orange-restricted**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 8.3, 8.8**
    - Generate rounded waits across all ranges plus null; assert label+color correctness and that `#FF8200` appears only with "Queue building"

  - [x] 3.3 Implement `formatLocalTime` in `src/lib/presentation.js`
    - Parse an ISO 8601 timestamp (explicit offset or `Z`) to an instant and render it in the viewer's local time zone as a 12-hour clock with AM/PM, no date, no seconds, no UTC offset
    - _Requirements: 5.4_

  - [x]* 3.4 Write property test for timestamp formatting
    - **Property 6: Timestamp renders as 12-hour local time without date, seconds, or offset**
    - **Validates: Requirements 5.4**
    - Generate valid ISO 8601 timestamps with assorted offsets and `Z`; assert output matches `^\d{1,2}:\d{2}\s(AM|PM)$`

  - [x]* 3.5 Write unit tests for queue-status and timestamp boundaries
    - Boundary examples: 10 → Normal, 11 → Moderate, 25 → Moderate, 26 → Queue building; `2026-06-12T13:45:00-08:00` and the same instant as `...Z` format to the same `h:mm AM/PM` string
    - _Requirements: 6.1, 6.2, 6.3, 5.4_

- [x] 4. Implement the card view model with the confidence gate
  - [x] 4.1 Implement `buildCardViewModel` in `src/lib/presentation.js`
    - Confidence gate: missing/null `confidence_score` or `< 0.5` → `LOW_CONFIDENCE` with `waitDisplay = null`, `queueStatus = "Data unavailable"/#54565A`, non-technical "estimate temporarily unavailable" copy and no jargon
    - Otherwise `POPULATED`: `waitDisplay.minutes = roundWaitMinutes(estimated_public_wait_minutes)` (withheld with "Data unavailable" if the estimate is null), `queueStatus = deriveQueueStatus(...)`, `openLanes = active_lanes`, `lastUpdated = formatLocalTime(timestamp)`, fixed `attribution`
    - Exclude `confidence_score`, `slowest_lane_id`, `average_inspection_minutes`, `average_queue_wait_minutes`, `throughput_per_hour`, `vehicles_in_bay`, and all raw field names from the model
    - _Requirements: 4.3, 5.1, 5.3, 5.5, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x]* 4.2 Write property test for the confidence gate
    - **Property 4: Confidence gating withholds low-confidence estimates**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 9.4**
    - Generate snapshots with confidence straddling 0.5 and missing `confidence_score`; assert LOW_CONFIDENCE withholding vs POPULATED behavior

  - [x]* 4.3 Write property test for populated-card field exclusivity
    - **Property 5: Populated card contains exactly the motorist-facing fields**
    - **Validates: Requirements 4.3, 5.1, 5.3, 5.5**
    - Generate acceptable-confidence snapshots; assert the motorist-facing fields are present and excluded fields/raw field names are absent

- [x] 5. Implement the interaction-state reducer
  - [x] 5.1 Implement `nextCardState` and the selector-state reducer in `src/lib/stateReducer.js`
    - Card reducer yields exactly one state from {loading, empty, low-confidence, error, populated}; a new-selection event always transitions to loading, clearing any prior loading/empty/error state
    - Once in the error state from a connection failure/timeout, remain in error until a later successful request clears it
    - Map outcomes: `200` → populated/low-confidence, `404` → empty (retain selection), network/timeout/other 4xx/5xx → error (retain selection); list outcomes: empty list → selector empty, network/timeout/4xx/5xx → selector error
    - _Requirements: 3.5, 3.6, 4.4, 4.5, 4.6, 9.3, 9.5_

  - [x]* 5.2 Write property test for outcome-to-state mapping
    - **Property 10: Request outcomes map to the correct interaction state**
    - **Validates: Requirements 3.5, 3.6, 4.5, 4.6**
    - Generate request outcomes for both endpoints; assert correct card/selector state and selection retention

  - [x]* 5.3 Write property test for single-state exclusivity and selection clearing
    - **Property 11: Exactly one card state is active and selection always clears the prior state**
    - **Validates: Requirements 4.4, 9.5**
    - Generate event sequences; assert exactly one active state and that selection routes through loading

  - [x]* 5.4 Write property test for error-state persistence
    - **Property 12: An error state persists until a later request succeeds**
    - **Validates: Requirements 9.3**
    - Generate outcome sequences; assert the error state persists until a subsequent success clears it

- [x] 6. Checkpoint - Ensure all presentation-logic tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement the Demo_Config loader and validation
  - [x] 7.1 Implement `loadDemoConfig` in `src/lib/config.js`
    - Read `apiBaseUrl` and `clientCredential` from the provided raw config (demo-only `window.OPUS_DEMO_CONFIG` via `config.js`); return `{ ok: true, config }` only when both are non-empty AND `apiBaseUrl` uses the `https:` scheme, else `{ ok: false }`
    - Hold the credential in memory for the API client header builder only; never write it into any view-facing string or URL
    - Provide `src/config.example.js` documenting the demo-only mechanism and the security constraint (credential exposed in a public static site is not production-safe)
    - _Requirements: 2.1, 2.4, 2.5, 2.6, 2.7_

  - [x]* 7.2 Write property test for invalid-configuration rejection
    - **Property 8: Invalid configuration is rejected and blocks all requests**
    - **Validates: Requirements 2.4, 2.5**
    - Generate configs with empty base URL, empty credential, or non-HTTPS base URL; assert validation fails and no request is issued

- [x] 8. Implement the API client
  - [x] 8.1 Implement `getStations` and `getStation` in `src/lib/apiClient.js`
    - Build request URLs from `config.apiBaseUrl`; refuse to send if the URL is not HTTPS (defense in depth)
    - Attach the `Client_Credential` as a request header; apply a 10-second timeout via `AbortController` (timeout → `FAILURE/timeout`)
    - Return the typed result `{ kind: "OK", body } | { kind: "NOT_FOUND" } | { kind: "FAILURE", reason }`; map `404` on the single-station path to `NOT_FOUND`
    - _Requirements: 1.4, 1.5, 2.2, 2.3, 4.5_

  - [x]* 8.2 Write property test for HTTPS + credential on every request
    - **Property 7: Every configured request is HTTPS and carries the credential**
    - **Validates: Requirements 2.2, 2.3, 1.4**
    - Generate valid configs and endpoints; inspect the constructed request to assert `https:` scheme and credential header

  - [x]* 8.3 Write property test for credential absence from displayed output
    - **Property 9: The credential never appears in viewer-visible output**
    - **Validates: Requirements 2.6**
    - Generate credential-like strings; assert no card view-model field, selector option text, status label, or displayed URL contains the credential value

  - [x]* 8.4 Write unit tests for the 10-second timeout
    - Assert a slow response aborts as a `FAILURE/timeout` at the 10-second boundary using fake timers
    - _Requirements: 1.5_

- [x] 9. Implement the DOM view
  - [x] 9.1 Implement `renderSelector` and `renderCard` in `src/app.js` (view layer)
    - `renderSelector(state, stations)` handles loading | populated(options) | empty | error; disable selector input while loading
    - `renderCard(cardState, viewModel)` handles loading | populated | low-confidence | empty | error; render every status color with its visible text label (never color alone); never show a numeric wait in loading/empty/low-confidence/error states
    - Empty card copy explains wait-time data will appear when station activity resumes; no internal model/detection/error terminology in non-populated states
    - _Requirements: 5.1, 6.5, 8.8, 9.1, 9.2, 9.4_

  - [x]* 9.2 Write property test for non-populated render safety
    - **Property 13: Non-populated states never show a numeric wait or internal terminology**
    - **Validates: Requirements 9.1, 9.2**
    - Generate loading/empty/low-confidence/error renders (jsdom); assert no numeric wait, no internal terminology, and the empty-state resume copy

- [x] 10. Implement the app controller and wire components together
  - [x] 10.1 Wire the lifecycle in `src/app.js`
    - On load: call `loadDemoConfig`; on `{ ok: false }` enter the NOT_CONFIGURED error state and issue no requests
    - On `{ ok: true }`: set the selector to loading (≤200ms) and disabled, request `GET /stations` within 1s of load, dedupe and populate (or empty/error per outcome)
    - On selection: set the card to loading within 500ms, request `GET /stations/{id}` within 200ms, build the view model and render populated/low-confidence/empty/error; changing selection clears prior card state first
    - Route all derivations through the presentation logic and all I/O through the API client; show exactly one card state at a time
    - _Requirements: 2.1, 2.4, 3.1, 3.4, 4.1, 4.2, 4.4, 9.1, 9.5_

  - [x]* 10.2 Write integration tests for wiring and external behavior
    - Using a stubbed API in jsdom: non-HTTPS base URL rejected before any fetch and configured fetches go to `https://…` (Req 1.4, 2.3, 2.5); credential attached to outgoing requests and absent from rendered DOM and displayed URLs (Req 2.2, 2.6); list fetch on load and snapshot fetch on selection (Req 3.1, 4.1)
    - 404 on the snapshot path renders empty and keeps selection; a 5xx renders error and keeps selection (Req 4.5, 4.6); error state persists across a failed request and clears after a later success (Req 9.3); empty list renders the selector empty state with zero options (Req 3.5)
    - _Requirements: 1.4, 2.2, 2.3, 2.5, 2.6, 3.1, 3.5, 4.1, 4.5, 4.6, 9.3_

- [ ] 11. Add snapshot, accessibility, and smoke tests
  - [ ]* 11.1 Write snapshot and accessibility tests
    - Snapshot the page shell asserting the Roboto stack with Arial/Helvetica/sans-serif fallback (Req 8.1), Opus palette tokens (Req 8.2), gradient hero (Req 8.5), Opus card style (Req 8.6), sentence-case headings (Req 8.4)
    - Run an automated contrast audit (axe) for ≥4.5:1 body text and ≥3:1 large text (Req 8.7); assert every status indicator pairs its color with a visible text label (Req 6.5, 8.8)
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 6.5, 8.8_

  - [x]* 11.2 Write smoke tests for the static deployable
    - Assert the deployable is a flat set of static assets with `index.html` as the index document and no server-side dependency beyond the API (Req 1.1, 1.3); verify the design records the demo-only credential constraint (Req 2.7)
    - _Requirements: 1.1, 1.3, 2.7_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Property tests use fast-check on Vitest, ≥100 examples each, mapped 1:1 to design Properties 1–13; the network is replaced with an in-memory fake client.
- Each task references specific requirement clauses for traceability.
- Checkpoints ensure incremental validation at natural breaks.
- The view never renders a numeric wait outside the populated state, and the credential never reaches any viewer-visible output.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "5.1", "7.1", "8.1"] },
    { "id": 2, "tasks": ["2.3", "2.2", "5.2", "5.3", "5.4", "7.2", "8.2", "8.4"] },
    { "id": 3, "tasks": ["3.1", "2.4"] },
    { "id": 4, "tasks": ["3.3", "3.2"] },
    { "id": 5, "tasks": ["4.1", "3.4", "3.5"] },
    { "id": 6, "tasks": ["9.1", "4.2", "4.3", "8.3"] },
    { "id": 7, "tasks": ["10.1", "9.2"] },
    { "id": 8, "tasks": ["10.2", "11.1", "11.2"] }
  ]
}
```
