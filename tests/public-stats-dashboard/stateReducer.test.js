import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { buildCardViewModel } from "../../src/lib/presentation.js";
import {
  cardStateFromStationOutcome,
  nextCardState,
  nextSelectorState,
  selectorStateFromListOutcome
} from "../../src/lib/stateReducer.js";

describe("public stats dashboard state reducers", () => {
  it("maps request outcomes to interaction states", () => {
    // Feature: public-stats-dashboard, Property 10: Request outcomes map to the correct interaction state
    fc.assert(
      fc.property(outcomeArb(), fc.constantFrom("station_a", "station_b"), (outcome, stationId) => {
        const loading = nextCardState(undefined, { type: "NEW_SELECTION", stationId });
        const state = cardStateFromStationOutcome(loading, outcome, buildCardViewModel);
        expect(state.selectedStationId).toBe(stationId);
        if (outcome.kind === "OK") {
          expect(["POPULATED", "LOW_CONFIDENCE"]).toContain(state.status);
        } else if (outcome.kind === "NOT_FOUND") {
          expect(state.status).toBe("EMPTY");
        } else {
          expect(state.status).toBe("ERROR");
        }
      }),
      { numRuns: 100 }
    );

    expect(selectorStateFromListOutcome(undefined, { kind: "OK", body: [] }, (body) => body).status).toBe("EMPTY");
    expect(selectorStateFromListOutcome(undefined, { kind: "FAILURE", reason: "network" }, (body) => body).status).toBe("ERROR");
  });

  it("keeps exactly one card state and clears on new selection", () => {
    // Feature: public-stats-dashboard, Property 11: Exactly one card state is active and selection always clears the prior state
    fc.assert(
      fc.property(fc.array(eventArb(), { minLength: 1, maxLength: 50 }), (events) => {
        let state = { status: "IDLE" };
        for (const event of events) {
          state = nextCardState(state, event);
          expect(typeof state.status).toBe("string");
          expect(Object.keys(state).filter((key) => ["LOADING", "EMPTY", "LOW_CONFIDENCE", "ERROR", "POPULATED"].includes(key))).toHaveLength(0);
          if (event.type === "NEW_SELECTION") {
            expect(state).toMatchObject({ status: "LOADING", selectedStationId: event.stationId });
          }
        }
      }),
      { numRuns: 100 }
    );
  });

  it("keeps error until a later successful request clears it", () => {
    // Feature: public-stats-dashboard, Property 12: An error state persists until a later request succeeds
    fc.assert(
      fc.property(fc.array(fc.constantFrom("failure", "not_found"), { minLength: 1, maxLength: 20 }), (outcomes) => {
        let state = nextCardState(undefined, { type: "NEW_SELECTION", stationId: "station_a" });
        state = nextCardState(state, { type: "SNAPSHOT_FAILURE", reason: "network" });
        expect(state.status).toBe("ERROR");

        for (const outcome of outcomes) {
          if (outcome === "failure") {
            state = nextCardState(state, { type: "SNAPSHOT_FAILURE", reason: "timeout" });
            expect(state.status).toBe("ERROR");
          } else {
            state = nextCardState(state, { type: "SNAPSHOT_NOT_FOUND" });
            expect(state.status).toBe("EMPTY");
            state = nextCardState(state, { type: "SNAPSHOT_FAILURE", reason: "network" });
            expect(state.status).toBe("ERROR");
          }
        }

        state = nextCardState(state, {
          type: "SNAPSHOT_OK",
          viewModel: buildCardViewModel({
            station_id: "station_a",
            timestamp: "2026-06-12T21:45:00Z",
            active_lanes: 2,
            estimated_public_wait_minutes: 8,
            confidence_score: 0.8
          })
        });
        expect(state.status).toBe("POPULATED");
      }),
      { numRuns: 100 }
    );
  });

  it("maps selector events", () => {
    expect(nextSelectorState(undefined, { type: "LOAD_STATIONS" })).toMatchObject({ status: "LOADING", stations: [] });
    expect(nextSelectorState(undefined, { type: "STATIONS_OK", stations: [{ station_id: "a" }] })).toMatchObject({ status: "POPULATED" });
    expect(nextSelectorState(undefined, { type: "STATIONS_OK", stations: [] })).toMatchObject({ status: "EMPTY", stations: [] });
    expect(nextSelectorState(undefined, { type: "STATIONS_FAILURE", reason: "timeout" })).toMatchObject({ status: "ERROR" });
  });
});

function outcomeArb() {
  return fc.oneof(
    fc.constant({
      kind: "OK",
      body: {
        station_id: "station_a",
        timestamp: "2026-06-12T21:45:00Z",
        active_lanes: 2,
        estimated_public_wait_minutes: 8,
        confidence_score: 0.8
      }
    }),
    fc.constant({ kind: "NOT_FOUND" }),
    fc.record({ kind: fc.constant("FAILURE"), reason: fc.constantFrom("network", "timeout", "http4xx", "http5xx") })
  );
}

function eventArb() {
  return fc.oneof(
    fc.record({ type: fc.constant("NEW_SELECTION"), stationId: fc.constantFrom("station_a", "station_b") }),
    fc.constant({ type: "SNAPSHOT_NOT_FOUND" }),
    fc.record({ type: fc.constant("SNAPSHOT_FAILURE"), reason: fc.constantFrom("network", "timeout", "http4xx", "http5xx") }),
    fc.constant({
      type: "SNAPSHOT_OK",
      viewModel: buildCardViewModel({
        station_id: "station_a",
        timestamp: "2026-06-12T21:45:00Z",
        active_lanes: 2,
        estimated_public_wait_minutes: 8,
        confidence_score: 0.8
      })
    })
  );
}
