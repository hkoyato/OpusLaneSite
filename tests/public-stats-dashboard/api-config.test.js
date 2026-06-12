import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import { buildRequest, getStation, getStations, CLIENT_CREDENTIAL_HEADER } from "../../src/lib/apiClient.js";
import { loadDemoConfig } from "../../src/lib/config.js";
import { buildCardViewModel } from "../../src/lib/presentation.js";

describe("public stats dashboard config and API client", () => {
  it("rejects invalid configuration before requests", () => {
    // Feature: public-stats-dashboard, Property 8: Invalid configuration is rejected and blocks all requests
    fc.assert(
      fc.property(
        fc.oneof(
          fc.record({ apiBaseUrl: fc.constant(""), clientCredential: fc.string({ minLength: 1 }) }),
          fc.record({ apiBaseUrl: fc.webUrl({ validSchemes: ["http"] }), clientCredential: fc.string({ minLength: 1 }) }),
          fc.record({ apiBaseUrl: fc.webUrl({ validSchemes: ["https"] }), clientCredential: fc.constant("") })
        ),
        (raw) => {
          expect(loadDemoConfig(raw).ok).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("builds HTTPS requests with the credential header", () => {
    // Feature: public-stats-dashboard, Property 7: Every configured request is HTTPS and carries the credential
    fc.assert(
      fc.property(validConfigArb(), fc.stringMatching(/^[a-z0-9_/-]{1,80}$/), (config, path) => {
        const built = buildRequest(config, path);
        expect(built.ok).toBe(true);
        expect(new URL(built.request.url).protocol).toBe("https:");
        expect(built.request.headers.get(CLIENT_CREDENTIAL_HEADER)).toBe(config.clientCredential);
      }),
      { numRuns: 100 }
    );
  });

  it("keeps credentials out of display strings", () => {
    // Feature: public-stats-dashboard, Property 9: The credential never appears in viewer-visible output
    fc.assert(
      fc.property(fc.uuid().map((value) => `SECRET_${value}`), (credential) => {
        const model = buildCardViewModel({
          station_id: "demo_station",
          timestamp: "2026-06-12T21:45:00Z",
          active_lanes: 3,
          estimated_public_wait_minutes: 12.5,
          confidence_score: 0.9
        });
        expect(JSON.stringify(model)).not.toContain(credential);
        expect("Demo Station Moderate wait Powered by Opus LaneSight").not.toContain(credential);
      }),
      { numRuns: 100 }
    );
  });

  it("maps HTTP outcomes and 404 absence correctly", async () => {
    const config = { apiBaseUrl: "https://api.example.test/prod", clientCredential: "demo" };
    await expect(getStations(config, async () => new Response("[]", { status: 200 }))).resolves.toEqual({ kind: "OK", body: [] });
    await expect(getStation(config, "missing", async () => new Response("{}", { status: 404 }))).resolves.toEqual({ kind: "NOT_FOUND" });
    await expect(getStation(config, "bad", async () => new Response("{}", { status: 403 }))).resolves.toEqual({ kind: "FAILURE", reason: "http4xx" });
    await expect(getStation(config, "down", async () => new Response("{}", { status: 502 }))).resolves.toEqual({ kind: "FAILURE", reason: "http5xx" });
  });

  it("times out slow requests after 10 seconds", async () => {
    vi.useFakeTimers();
    const config = { apiBaseUrl: "https://api.example.test/prod", clientCredential: "demo" };
    const fetchImpl = vi.fn((request, init) => new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));

    const result = getStations(config, fetchImpl);
    await vi.advanceTimersByTimeAsync(10000);
    await expect(result).resolves.toEqual({ kind: "FAILURE", reason: "timeout" });
    vi.useRealTimers();
  });
});

function validConfigArb() {
  return fc.record({
    apiBaseUrl: fc.webUrl({ validSchemes: ["https"] }),
    clientCredential: fc.uuid().map((value) => `cred-${value}`)
  });
}
