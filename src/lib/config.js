export function loadDemoConfig(raw) {
  const apiBaseUrl = typeof raw?.apiBaseUrl === "string" ? raw.apiBaseUrl.trim() : "";
  const clientCredential = typeof raw?.clientCredential === "string" ? raw.clientCredential.trim() : "";

  if (!apiBaseUrl || !clientCredential) {
    return { ok: false };
  }

  try {
    const parsed = new URL(apiBaseUrl);
    if (parsed.protocol !== "https:") {
      return { ok: false };
    }
    return {
      ok: true,
      config: {
        apiBaseUrl: parsed.toString().replace(/\/$/, ""),
        clientCredential
      }
    };
  } catch {
    return { ok: false };
  }
}
