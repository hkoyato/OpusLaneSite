import { getStation, getStations } from "./lib/apiClient.js";
import { loadDemoConfig } from "./lib/config.js";
import { buildCardViewModel, dedupeStations, formatStationName } from "./lib/presentation.js";
import { cardStateFromStationOutcome, nextCardState, nextSelectorState, selectorStateFromListOutcome } from "./lib/stateReducer.js";

const INTERNAL_TERMS = ["confidence", "model", "detection", "score", "raw", "slowest", "throughput"];

export function renderSelector(state, stations = [], root = document) {
  const select = root.getElementById("station-select");
  const stateText = root.getElementById("selector-state");
  if (!select || !stateText) {
    return;
  }

  const status = typeof state === "string" ? state : state?.status;
  select.replaceChildren();

  if (status === "LOADING") {
    select.disabled = true;
    select.append(option("", "Loading stations..."));
    stateText.textContent = "Loading available stations.";
    return;
  }

  if (status === "EMPTY") {
    select.disabled = true;
    select.append(option("", "No stations available"));
    stateText.textContent = "No stations are currently publishing wait-time data.";
    return;
  }

  if (status === "ERROR") {
    select.disabled = true;
    select.append(option("", "Stations unavailable"));
    stateText.textContent = "Station data is currently unavailable.";
    return;
  }

  select.disabled = false;
  select.append(option("", "Select a station"));
  for (const station of stations) {
    select.append(option(station.station_id, formatStationName(station.station_id)));
  }
  stateText.textContent = "Select a station to view current wait-time information.";
}

export function renderCard(cardState, viewModel, root = document) {
  const card = root.getElementById("wait-card");
  if (!card) {
    return;
  }

  const status = typeof cardState === "string" ? cardState : cardState?.status;
  resetCardClasses(card);
  card.replaceChildren();
  card.append(heading("Station wait time"));

  if (status === "LOADING") {
    card.append(stateBlock("loading-state", "Loading station details", "The latest wait-time information is loading."));
    card.querySelector(".loading-state")?.append(loadingBar());
    return;
  }

  if (status === "EMPTY") {
    card.classList.add("status-unavailable");
    card.append(stateBlock("empty-state", "No current wait-time data", "Wait-time data will appear when station activity resumes."));
    return;
  }

  if (status === "ERROR") {
    card.classList.add("status-unavailable");
    card.append(stateBlock("error-state", "Service currently unavailable", "Wait-time data is currently unavailable. Please check again soon."));
    return;
  }

  if (status === "LOW_CONFIDENCE" && viewModel) {
    card.classList.add("status-unavailable");
    card.append(statusChip(viewModel.queueStatus));
    card.append(stateBlock("low-confidence-state", viewModel.stationName, viewModel.message));
    card.append(detailsGrid(viewModel));
    card.append(attribution(viewModel.attribution));
    return;
  }

  if (status === "POPULATED" && viewModel) {
    card.classList.add(`status-${viewModel.queueStatus.tone}`);
    const title = document.createElement("h3");
    title.className = "station-name";
    title.textContent = viewModel.stationName;
    card.append(title);
    card.append(statusChip(viewModel.queueStatus));

    if (viewModel.waitDisplay) {
      const row = document.createElement("div");
      row.className = "wait-value-row";
      const value = document.createElement("span");
      value.className = "wait-value";
      value.textContent = String(viewModel.waitDisplay.minutes);
      const unit = document.createElement("span");
      unit.className = "wait-unit";
      unit.textContent = viewModel.waitDisplay.label;
      row.append(value, unit);
      card.append(row);
    } else {
      card.append(stateBlock("empty-state", "Estimate unavailable", "Wait-time data will appear when station activity resumes."));
    }

    card.append(detailsGrid(viewModel));
    card.append(attribution(viewModel.attribution));
    return;
  }

  card.append(stateBlock("empty-state", "Select a station", "Wait-time data will appear here when a station is selected."));
}

export function startApp({ root = document, configSource = globalThis.window?.OPUS_DEMO_CONFIG, api = { getStations, getStation } } = {}) {
  const loaded = loadDemoConfig(configSource);
  let selectorState = nextSelectorState(undefined, { type: "LOAD_STATIONS" });
  let cardState = { status: "IDLE" };
  let requestToken = 0;

  if (!loaded.ok) {
    renderSelector({ status: "ERROR" }, [], root);
    renderCard({ status: "ERROR" }, null, root);
    const selectorText = root.getElementById("selector-state");
    if (selectorText) {
      selectorText.textContent = "This demo is not configured.";
    }
    return { stop() {}, getState: () => ({ selectorState, cardState }) };
  }

  const config = loaded.config;
  renderSelector(selectorState, [], root);

  api.getStations(config).then((outcome) => {
    selectorState = selectorStateFromListOutcome(selectorState, outcome, dedupeStations);
    renderSelector(selectorState, selectorState.stations, root);
  });

  const select = root.getElementById("station-select");
  const onChange = () => {
    const stationId = select?.value;
    if (!stationId) {
      cardState = { status: "IDLE" };
      renderCard(cardState, null, root);
      return;
    }

    const token = ++requestToken;
    cardState = nextCardState(cardState, { type: "NEW_SELECTION", stationId });
    renderCard(cardState, null, root);

    api.getStation(config, stationId).then((outcome) => {
      if (token !== requestToken) {
        return;
      }
      cardState = cardStateFromStationOutcome(cardState, outcome, buildCardViewModel);
      renderCard(cardState, cardState.viewModel, root);
    });
  };

  select?.addEventListener("change", onChange);

  return {
    stop() {
      select?.removeEventListener("change", onChange);
    },
    getState: () => ({ selectorState, cardState })
  };
}

function option(value, label) {
  const optionElement = document.createElement("option");
  optionElement.value = value;
  optionElement.textContent = label;
  return optionElement;
}

function heading(text) {
  const element = document.createElement("h2");
  element.id = "wait-card-title";
  element.textContent = text;
  return element;
}

function resetCardClasses(card) {
  card.classList.remove("status-normal", "status-moderate", "status-attention", "status-unavailable");
}

function statusChip(queueStatus) {
  const chip = document.createElement("div");
  chip.className = "status-chip";
  chip.style.setProperty("--status-color", queueStatus.color);
  const dot = document.createElement("span");
  dot.className = "status-dot";
  dot.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.textContent = queueStatus.label;
  chip.append(dot, label);
  return chip;
}

function stateBlock(className, title, copy) {
  const wrapper = document.createElement("div");
  wrapper.className = className;
  const titleElement = document.createElement("p");
  titleElement.className = "state-title";
  titleElement.textContent = scrubInternalTerms(title);
  const copyElement = document.createElement("p");
  copyElement.className = "state-copy";
  copyElement.textContent = scrubInternalTerms(copy);
  wrapper.append(titleElement, copyElement);
  return wrapper;
}

function loadingBar() {
  const bar = document.createElement("div");
  bar.className = "loading-bar";
  bar.setAttribute("aria-hidden", "true");
  return bar;
}

function detailsGrid(viewModel) {
  const grid = document.createElement("div");
  grid.className = "details-grid";
  grid.append(detailCard("Open lanes", String(viewModel.openLanes)));
  grid.append(detailCard("Last updated", viewModel.lastUpdated));
  return grid;
}

function detailCard(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "detail-card";
  const labelElement = document.createElement("p");
  labelElement.className = "detail-label";
  labelElement.textContent = label;
  const valueElement = document.createElement("p");
  valueElement.className = "detail-value";
  valueElement.textContent = value;
  wrapper.append(labelElement, valueElement);
  return wrapper;
}

function attribution(text) {
  const element = document.createElement("p");
  element.className = "attribution";
  element.textContent = text;
  return element;
}

function scrubInternalTerms(text) {
  const value = String(text ?? "");
  for (const term of INTERNAL_TERMS) {
    if (value.toLowerCase().includes(term)) {
      return "Wait-time information is currently unavailable.";
    }
  }
  return value;
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => startApp());
}
