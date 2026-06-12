export const REQUEST_TIMEOUT_MS = 10_000;
export const CLIENT_CREDENTIAL_HEADER = "X-Client-Credential";

export function buildRequest(config, path) {
  const baseUrl = normalizeHttpsBaseUrl(config?.apiBaseUrl);
  if (!baseUrl.ok) {
    return { ok: false, reason: "network" };
  }

  const url = new URL(path.replace(/^\/+/, ""), `${baseUrl.value}/`);
  if (url.protocol !== "https:") {
    return { ok: false, reason: "network" };
  }

  const headers = new Headers();
  headers.set(CLIENT_CREDENTIAL_HEADER, String(config.clientCredential));
  headers.set("Accept", "application/json");

  return {
    ok: true,
    request: new Request(url.toString(), {
      method: "GET",
      headers
    })
  };
}

export async function getStations(config, fetchImpl = globalThis.fetch) {
  return requestJson(config, "stations", { fetchImpl, notFoundIsAbsence: false });
}

export async function getStation(config, stationId, fetchImpl = globalThis.fetch) {
  const encoded = encodeURIComponent(stationId);
  return requestJson(config, `stations/${encoded}`, { fetchImpl, notFoundIsAbsence: true });
}

async function requestJson(config, path, { fetchImpl, notFoundIsAbsence }) {
  const built = buildRequest(config, path);
  if (!built.ok || typeof fetchImpl !== "function") {
    return { kind: "FAILURE", reason: built.reason ?? "network" };
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetchImpl(built.request, { signal: controller.signal });
    if (response.status === 404 && notFoundIsAbsence) {
      return { kind: "NOT_FOUND" };
    }
    if (!response.ok) {
      return { kind: "FAILURE", reason: response.status >= 500 ? "http5xx" : "http4xx" };
    }
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { kind: "OK", body };
  } catch (error) {
    return { kind: "FAILURE", reason: error?.name === "AbortError" ? "timeout" : "network" };
  } finally {
    clearTimeout(timeoutId);
  }
}

function normalizeHttpsBaseUrl(value) {
  try {
    const url = new URL(String(value ?? ""));
    if (url.protocol !== "https:") {
      return { ok: false };
    }
    return { ok: true, value: url.toString().replace(/\/$/, "") };
  } catch {
    return { ok: false };
  }
}
