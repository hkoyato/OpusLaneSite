import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildCardViewModel } from "../../src/lib/presentation.js";
import { renderCard, renderSelector, startApp } from "../../src/app.js";

describe("public stats dashboard DOM rendering and wiring", () => {
  beforeEach(() => {
    document.body.innerHTML = fixtureHtml();
  });

  it("keeps non-populated states free of wait values and internal terminology", () => {
    // Feature: public-stats-dashboard, Property 13: Non-populated states never show a numeric wait or internal terminology
    fc.assert(
      fc.property(fc.constantFrom("LOADING", "EMPTY", "ERROR"), (status) => {
        document.body.innerHTML = fixtureHtml();
        renderCard({ status }, null, document);
        expect(document.querySelector(".wait-value")).toBeNull();
        expect(document.body.textContent.toLowerCase()).not.toMatch(/confidence|model|detection|score/);
        if (status === "EMPTY") {
          expect(document.body.textContent).toContain("Wait-time data will appear when station activity resumes.");
        }
      }),
      { numRuns: 100 }
    );

    const lowConfidence = buildCardViewModel({
      station_id: "station_a",
      timestamp: "2026-06-12T21:45:00Z",
      active_lanes: 2,
      estimated_public_wait_minutes: 9,
      confidence_score: 0.1
    });
    renderCard({ status: "LOW_CONFIDENCE" }, lowConfidence, document);
    expect(document.querySelector(".wait-value")).toBeNull();
    expect(document.body.textContent.toLowerCase()).not.toMatch(/confidence|model|detection|score/);
  });

  it("renders selector states and deduped options", () => {
    renderSelector({ status: "LOADING" }, [], document);
    expect(document.getElementById("station-select").disabled).toBe(true);

    renderSelector({ status: "POPULATED" }, [{ station_id: "demo_station" }], document);
    expect(document.getElementById("station-select").disabled).toBe(false);
    expect([...document.querySelectorAll("option")].map((node) => node.textContent)).toContain("Demo Station");

    renderSelector({ status: "EMPTY" }, [], document);
    expect(document.getElementById("selector-state").textContent).toContain("No stations");
  });

  it("wires load, selection, 404, failure, and later success", async () => {
    const config = { apiBaseUrl: "https://api.example.test/prod", clientCredential: "demo-secret" };
    const api = {
      getStations: vi.fn(async () => ({ kind: "OK", body: [{ station_id: "station_a" }, { station_id: "station_a" }, { station_id: "station_b" }] })),
      getStation: vi
        .fn()
        .mockResolvedValueOnce({ kind: "NOT_FOUND" })
        .mockResolvedValueOnce({ kind: "FAILURE", reason: "http5xx" })
        .mockResolvedValueOnce({
          kind: "OK",
          body: {
            station_id: "station_b",
            timestamp: "2026-06-12T21:45:00Z",
            active_lanes: 4,
            estimated_public_wait_minutes: 12.5,
            confidence_score: 0.9
          }
        })
    };

    startApp({ root: document, configSource: config, api });
    await Promise.resolve();

    expect(api.getStations).toHaveBeenCalledWith(config);
    expect([...document.querySelectorAll("#station-select option")]).toHaveLength(3);

    const select = document.getElementById("station-select");
    select.value = "station_a";
    select.dispatchEvent(new Event("change"));
    await Promise.resolve();
    expect(document.body.textContent).toContain("No current wait-time data");
    expect(select.value).toBe("station_a");

    select.value = "station_b";
    select.dispatchEvent(new Event("change"));
    await Promise.resolve();
    expect(document.body.textContent).toContain("Service currently unavailable");
    expect(select.value).toBe("station_b");

    select.dispatchEvent(new Event("change"));
    await Promise.resolve();
    expect(document.body.textContent).toContain("Moderate wait");
    expect(document.body.textContent).toContain("13");
    expect(document.body.textContent).not.toContain("demo-secret");
  });

  it("rejects non-HTTPS config before fetch", () => {
    const api = { getStations: vi.fn(), getStation: vi.fn() };
    startApp({ root: document, configSource: { apiBaseUrl: "http://api.example.test", clientCredential: "secret" }, api });
    expect(api.getStations).not.toHaveBeenCalled();
    expect(document.getElementById("selector-state").textContent).toBe("This demo is not configured.");
  });
});

function fixtureHtml() {
  return `
    <p id="selector-state"></p>
    <select id="station-select"></select>
    <section id="wait-card" class="wait-card card"></section>
  `;
}
