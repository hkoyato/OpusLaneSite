import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  ATTRIBUTION,
  STATUS_COLORS,
  buildCardViewModel,
  dedupeStations,
  deriveQueueStatus,
  formatLocalTime,
  roundWaitMinutes
} from "../../src/lib/presentation.js";

const stationIdArb = fc.stringMatching(/^[a-z0-9_-]{1,24}$/);

describe("public stats dashboard presentation logic", () => {
  it("deduplicates stations by first occurrence", () => {
    // Feature: public-stats-dashboard, Property 1: Station de-duplication keeps first occurrence and preserves order
    fc.assert(
      fc.property(
        fc.array(fc.record({ station_id: stationIdArb, timestamp: fc.date().map((date) => date.toISOString()) }), { maxLength: 500 }),
        (stations) => {
          const deduped = dedupeStations(stations);
          const firstSeen = [];
          const seen = new Set();
          for (const station of stations) {
            if (!seen.has(station.station_id)) {
              seen.add(station.station_id);
              firstSeen.push(station);
            }
          }
          expect(deduped).toEqual(firstSeen);
          expect(new Set(deduped.map((station) => station.station_id)).size).toBe(deduped.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("rounds waits half-up to non-negative whole minutes", () => {
    // Feature: public-stats-dashboard, Property 2: Wait rounding is round-half-up to a non-negative integer
    fc.assert(
      fc.property(fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }), (value) => {
        const rounded = roundWaitMinutes(value);
        expect(rounded).toBe(Math.floor(value + 0.5));
        expect(Number.isInteger(rounded)).toBe(true);
        expect(rounded).toBeGreaterThanOrEqual(0);
      }),
      { numRuns: 100 }
    );

    expect(roundWaitMinutes(null)).toBeNull();
    expect(roundWaitMinutes(Number.NaN)).toBeNull();
    expect(roundWaitMinutes(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("derives labelled queue status across all ranges", () => {
    // Feature: public-stats-dashboard, Property 3: Queue status is correct across all ranges, always labelled, and orange-restricted
    fc.assert(
      fc.property(fc.option(fc.integer({ min: 0, max: 100000 }), { nil: null }), (wait) => {
        const status = deriveQueueStatus(wait);
        expect(status.label).not.toEqual("");
        expect(status.color).toMatch(/^#[0-9A-F]{6}$/);

        if (wait === null) {
          expect(status).toMatchObject({ label: "Data unavailable", color: STATUS_COLORS.unavailable });
        } else if (wait <= 10) {
          expect(status).toMatchObject({ label: "Normal wait", color: STATUS_COLORS.normal });
        } else if (wait <= 25) {
          expect(status).toMatchObject({ label: "Moderate wait", color: STATUS_COLORS.moderate });
        } else {
          expect(status).toMatchObject({ label: "Queue building", color: STATUS_COLORS.attention });
        }

        if (status.color === STATUS_COLORS.attention) {
          expect(status.label).toBe("Queue building");
        }
      }),
      { numRuns: 100 }
    );

    expect(deriveQueueStatus(10)).toMatchObject({ label: "Normal wait" });
    expect(deriveQueueStatus(11)).toMatchObject({ label: "Moderate wait" });
    expect(deriveQueueStatus(25)).toMatchObject({ label: "Moderate wait" });
    expect(deriveQueueStatus(26)).toMatchObject({ label: "Queue building" });
  });

  it("formats timestamps as local 12-hour times", () => {
    // Feature: public-stats-dashboard, Property 6: Timestamp renders as 12-hour local time without date, seconds, or offset
    fc.assert(
      fc.property(fc.date(), (date) => {
        expect(formatLocalTime(date.toISOString())).toMatch(/^\d{1,2}:\d{2}\s(AM|PM)$/);
      }),
      { numRuns: 100 }
    );

    const withOffset = formatLocalTime("2026-06-12T13:45:00-08:00");
    const sameInstant = formatLocalTime("2026-06-12T21:45:00Z");
    expect(withOffset).toBe(sameInstant);
    expect(withOffset).not.toMatch(/\d{4}|UTC|GMT|[+-]\d{2}:\d{2}/);
  });

  it("withholds low-confidence estimates", () => {
    // Feature: public-stats-dashboard, Property 4: Confidence gating withholds low-confidence estimates
    fc.assert(
      fc.property(snapshotArb(), fc.oneof(fc.double({ min: 0, max: 0.4999, noNaN: true }), fc.constant(null)), (snapshot, confidence) => {
        if (confidence === null) {
          delete snapshot.confidence_score;
        } else {
          snapshot.confidence_score = confidence;
        }
        const model = buildCardViewModel(snapshot);
        expect(model.state).toBe("LOW_CONFIDENCE");
        expect(model.waitDisplay).toBeNull();
        expect(model.queueStatus).toMatchObject({ label: "Data unavailable", color: STATUS_COLORS.unavailable });
        expect(`${model.message} ${model.queueStatus.label}`.toLowerCase()).not.toMatch(/confidence|score|model|raw/);
      }),
      { numRuns: 100 }
    );

    fc.assert(
      fc.property(snapshotArb(), fc.double({ min: 0.5, max: 1, noNaN: true }), (snapshot, confidence) => {
        snapshot.confidence_score = confidence;
        const model = buildCardViewModel(snapshot);
        expect(model.state).toBe("POPULATED");
        expect(model.waitDisplay?.minutes).toBe(roundWaitMinutes(snapshot.estimated_public_wait_minutes));
        expect(model.queueStatus).toEqual(deriveQueueStatus(model.waitDisplay.minutes));
      }),
      { numRuns: 100 }
    );
  });

  it("returns only motorist-facing populated card fields", () => {
    // Feature: public-stats-dashboard, Property 5: Populated card contains exactly the motorist-facing fields
    fc.assert(
      fc.property(snapshotArb(), (snapshot) => {
        snapshot.confidence_score = 0.75;
        const model = buildCardViewModel(snapshot);
        const serialized = JSON.stringify(model);
        expect(model).toMatchObject({
          state: "POPULATED",
          attribution: ATTRIBUTION,
          openLanes: snapshot.active_lanes
        });
        expect(model.stationName).not.toEqual("");
        expect(model.waitDisplay.label).toBe("minutes");
        expect(model.queueStatus.label).not.toEqual("");
        expect(model.lastUpdated).toMatch(/^\d{1,2}:\d{2}\s(AM|PM)$/);
        for (const forbidden of [
          "confidence_score",
          "slowest_lane_id",
          "average_inspection_minutes",
          "average_queue_wait_minutes",
          "throughput_per_hour",
          "vehicles_in_bay"
        ]) {
          expect(serialized).not.toContain(forbidden);
        }
      }),
      { numRuns: 100 }
    );
  });
});

function snapshotArb() {
  return fc.record({
    station_id: stationIdArb,
    timestamp: fc.date().map((date) => date.toISOString()),
    active_lanes: fc.integer({ min: 0, max: 30 }),
    estimated_public_wait_minutes: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    confidence_score: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
    vehicles_in_bay: fc.integer({ min: 0, max: 1000 }),
    average_queue_wait_minutes: fc.double({ min: 0, max: 1000, noNaN: true }),
    average_inspection_minutes: fc.double({ min: 0, max: 1000, noNaN: true }),
    throughput_per_hour: fc.double({ min: 0, max: 1000, noNaN: true }),
    slowest_lane_id: fc.stringMatching(/^[a-z0-9_-]{1,12}$/)
  });
}
