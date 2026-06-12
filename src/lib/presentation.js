export const STATUS_COLORS = Object.freeze({
  normal: "#93D500",
  moderate: "#00A0E0",
  attention: "#FF8200",
  unavailable: "#54565A"
});

export const CONFIDENCE_THRESHOLD = 0.5;
export const ATTRIBUTION = "Powered by Opus LaneSight";

export function dedupeStations(list) {
  const seen = new Set();
  const result = [];

  for (const entry of Array.isArray(list) ? list : []) {
    const stationId = entry?.station_id;
    if (typeof stationId !== "string" || seen.has(stationId)) {
      continue;
    }
    seen.add(stationId);
    result.push(entry);
  }

  return result;
}

export function roundWaitMinutes(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.max(0, Math.floor(numeric + 0.5));
}

export function deriveQueueStatus(roundedWait) {
  if (!Number.isInteger(roundedWait) || roundedWait < 0) {
    return { label: "Data unavailable", color: STATUS_COLORS.unavailable, tone: "unavailable" };
  }
  if (roundedWait <= 10) {
    return { label: "Normal wait", color: STATUS_COLORS.normal, tone: "normal" };
  }
  if (roundedWait <= 25) {
    return { label: "Moderate wait", color: STATUS_COLORS.moderate, tone: "moderate" };
  }
  return { label: "Queue building", color: STATUS_COLORS.attention, tone: "attention" };
}

export function formatLocalTime(iso8601) {
  const date = new Date(iso8601);
  if (Number.isNaN(date.getTime())) {
    return "Unavailable";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  }).format(date);
}

export function formatStationName(stationId) {
  if (typeof stationId !== "string" || stationId.trim() === "") {
    return "Selected station";
  }
  return stationId
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .split(" ")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}

export function buildCardViewModel(snapshot, threshold = CONFIDENCE_THRESHOLD) {
  const confidence = snapshot?.confidence_score;
  const isAcceptableConfidence = typeof confidence === "number" && Number.isFinite(confidence) && confidence >= threshold;
  const stationName = formatStationName(snapshot?.station_id);
  const lastUpdated = formatLocalTime(snapshot?.timestamp);
  const openLanes = wholeNumberCount(snapshot?.active_lanes);

  if (!isAcceptableConfidence) {
    return {
      state: "LOW_CONFIDENCE",
      stationName,
      waitDisplay: null,
      queueStatus: deriveQueueStatus(null),
      openLanes,
      lastUpdated,
      message: "A wait-time estimate is temporarily unavailable for this station.",
      attribution: ATTRIBUTION
    };
  }

  const roundedWait = roundWaitMinutes(snapshot?.estimated_public_wait_minutes);
  return {
    state: "POPULATED",
    stationName,
    waitDisplay: roundedWait === null ? null : { minutes: roundedWait, label: "minutes" },
    queueStatus: deriveQueueStatus(roundedWait),
    openLanes,
    lastUpdated,
    attribution: ATTRIBUTION
  };
}

function wholeNumberCount(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return Math.max(0, Math.trunc(numeric));
}
