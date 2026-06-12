export const CARD_STATES = Object.freeze(["IDLE", "LOADING", "POPULATED", "LOW_CONFIDENCE", "EMPTY", "ERROR"]);
export const SELECTOR_STATES = Object.freeze(["LOADING", "POPULATED", "EMPTY", "ERROR"]);

export function nextCardState(current, event) {
  switch (event?.type) {
    case "NEW_SELECTION":
      return { status: "LOADING", selectedStationId: event.stationId };
    case "SNAPSHOT_OK":
      return {
        status: event.viewModel?.state === "LOW_CONFIDENCE" ? "LOW_CONFIDENCE" : "POPULATED",
        selectedStationId: current?.selectedStationId,
        viewModel: event.viewModel
      };
    case "SNAPSHOT_NOT_FOUND":
      return { status: "EMPTY", selectedStationId: current?.selectedStationId };
    case "SNAPSHOT_FAILURE":
      return { status: "ERROR", selectedStationId: current?.selectedStationId, reason: event.reason };
    default:
      return current ?? { status: "IDLE" };
  }
}

export function nextSelectorState(current, event) {
  switch (event?.type) {
    case "LOAD_STATIONS":
      return { status: "LOADING", stations: [] };
    case "STATIONS_OK":
      return Array.isArray(event.stations) && event.stations.length > 0
        ? { status: "POPULATED", stations: event.stations }
        : { status: "EMPTY", stations: [] };
    case "STATIONS_FAILURE":
      return { status: "ERROR", stations: [], reason: event.reason };
    default:
      return current ?? { status: "LOADING", stations: [] };
  }
}

export function cardStateFromStationOutcome(current, outcome, buildViewModel) {
  if (outcome?.kind === "OK") {
    return nextCardState(current, { type: "SNAPSHOT_OK", viewModel: buildViewModel(outcome.body) });
  }
  if (outcome?.kind === "NOT_FOUND") {
    return nextCardState(current, { type: "SNAPSHOT_NOT_FOUND" });
  }
  return nextCardState(current, { type: "SNAPSHOT_FAILURE", reason: outcome?.reason ?? "network" });
}

export function selectorStateFromListOutcome(current, outcome, normalizeStations) {
  if (outcome?.kind === "OK") {
    return nextSelectorState(current, { type: "STATIONS_OK", stations: normalizeStations(outcome.body) });
  }
  return nextSelectorState(current, { type: "STATIONS_FAILURE", reason: outcome?.reason ?? "network" });
}
