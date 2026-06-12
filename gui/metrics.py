"""Station wait-time formula and metrics aggregation for Opus LaneSight.

This module is the deterministic "station intelligence" layer. It converts the
per-vehicle :class:`gui.models.TrackResult` list produced by the tracking
pipeline into station-level operational metrics and a public wait-time
estimate.

Design notes
------------
- Pure, deterministic functions only. No I/O, no pipeline modification.
- The public wait-time estimate is a transparent formula (Product Overview
  section 12) so judges and operators can reason about it:

      estimated_public_wait = queue_depth * avg_inspection_minutes / active_lanes

- Where the raw tracking output does not yet provide zone/lane semantics,
  metrics are grounded in values that ARE derivable from the data:
  peak concurrent vehicles (queue-depth proxy), completed-vehicle inspection
  durations, and throughput over the observed window.
- The LLM (Bedrock) summary, when added, must consume these calculated metrics
  rather than invent its own — keeping the wait-time deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gui.models import TrackResult

# Status thresholds (minutes) for the public wait-time classification.
# Aligned with the UI status system in ui_guidelines.md section 5.
_MODERATE_THRESHOLD_MINUTES = 10.0
_ATTENTION_THRESHOLD_MINUTES = 20.0

# Status keys map to the UI status-color system (Normal/Moderate/Attention).
STATUS_NORMAL = "normal"
STATUS_MODERATE = "moderate"
STATUS_ATTENTION = "attention"
STATUS_UNKNOWN = "unknown"

_STATUS_LABELS = {
    STATUS_NORMAL: "Normal wait",
    STATUS_MODERATE: "Moderate wait",
    STATUS_ATTENTION: "Queue building",
    STATUS_UNKNOWN: "Data unavailable",
}


@dataclass
class StationMetrics:
    """Aggregate operational metrics for a single station snapshot.

    Field names mirror the Station metric snapshot in the product overview
    (section 11) so this maps cleanly onto a future JSON API / DynamoDB item
    and the Bedrock summary prompt.
    """

    station_name: str
    total_vehicles: int
    vehicles_in_queue: int  # peak concurrent vehicles (queue-depth proxy)
    completed_vehicles: int  # vehicles that entered and left the frame
    active_lanes: int
    average_inspection_minutes: float | None
    average_queue_wait_minutes: float | None
    estimated_public_wait_minutes: int | None
    throughput_per_hour: float
    observed_duration_minutes: float
    status: str = STATUS_UNKNOWN
    status_label: str = field(default=_STATUS_LABELS[STATUS_UNKNOWN])

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict (for API output / Bedrock input)."""
        return {
            "station_name": self.station_name,
            "total_vehicles": self.total_vehicles,
            "vehicles_in_queue": self.vehicles_in_queue,
            "completed_vehicles": self.completed_vehicles,
            "active_lanes": self.active_lanes,
            "average_inspection_minutes": self.average_inspection_minutes,
            "average_queue_wait_minutes": self.average_queue_wait_minutes,
            "estimated_public_wait_minutes": self.estimated_public_wait_minutes,
            "throughput_per_hour": self.throughput_per_hour,
            "observed_duration_minutes": self.observed_duration_minutes,
            "status": self.status,
            "status_label": self.status_label,
        }


def estimate_public_wait(
    queue_depth: int,
    avg_inspection_minutes: float,
    active_lanes: int,
) -> float:
    """Compute the estimated public wait time in minutes (unrounded).

    Implements the transparent formula from the product overview:

        estimated_public_wait = queue_depth * avg_inspection_minutes / active_lanes

    Returns 0.0 when the queue is empty or the average inspection duration is
    non-positive. ``active_lanes`` is floored at 1 to avoid division by zero
    (a station with zero active lanes is treated as a single serving lane for
    estimation purposes).

    The result is always non-negative.
    """
    if queue_depth <= 0 or avg_inspection_minutes <= 0:
        return 0.0
    lanes = max(1, active_lanes)
    return (queue_depth * avg_inspection_minutes) / lanes


def round_public_wait(minutes: float) -> int:
    """Round a wait estimate to a motorist-friendly whole number of minutes.

    Public-facing copy uses "18 minutes", never "18.42 minutes"
    (ui_guidelines.md section 11). A positive estimate below one minute is
    surfaced as 1 minute so motorists are never shown "0 minutes" while
    vehicles are still queueing.
    """
    if minutes <= 0:
        return 0
    return max(1, round(minutes))


def classify_status(wait_minutes: float | None) -> tuple[str, str]:
    """Classify a wait estimate into a (status_key, label) pair.

    - ``None`` -> unknown / "Data unavailable"
    - < 10 min -> normal / "Normal wait"
    - < 20 min -> moderate / "Moderate wait"
    - >= 20 min -> attention / "Queue building"
    """
    if wait_minutes is None:
        return STATUS_UNKNOWN, _STATUS_LABELS[STATUS_UNKNOWN]
    if wait_minutes < _MODERATE_THRESHOLD_MINUTES:
        return STATUS_NORMAL, _STATUS_LABELS[STATUS_NORMAL]
    if wait_minutes < _ATTENTION_THRESHOLD_MINUTES:
        return STATUS_MODERATE, _STATUS_LABELS[STATUS_MODERATE]
    return STATUS_ATTENTION, _STATUS_LABELS[STATUS_ATTENTION]


def peak_concurrent_vehicles(results: list[TrackResult]) -> int:
    """Return the maximum number of vehicles present simultaneously.

    Uses a sweep line over enter/leave events. This is a grounded proxy for
    queue depth: the busiest moment in the observed window. Vehicles that
    never left the frame (``leave_time is None``) are treated as present from
    their enter time through the end of the observation.

    Returns 0 for an empty result set.
    """
    if not results:
        return 0

    # Determine the end-of-observation time for still-present vehicles.
    end_time = max(
        (r.leave_time if r.leave_time is not None else r.enter_time)
        for r in results
    )

    # Build (+1 on enter, -1 on leave) events. Ties: process leaves before
    # enters at the same timestamp so back-to-back vehicles don't inflate peak.
    events: list[tuple[float, int]] = []
    for r in results:
        events.append((r.enter_time, 1))
        leave = r.leave_time if r.leave_time is not None else end_time
        events.append((leave, -1))

    events.sort(key=lambda e: (e[0], e[1]))

    current = 0
    peak = 0
    for _time, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def compute_throughput_per_hour(
    completed_vehicles: int, observed_duration_seconds: float
) -> float:
    """Vehicles processed per hour over the observed window.

    Returns 0.0 when the observed duration is non-positive.
    """
    if observed_duration_seconds <= 0:
        return 0.0
    return completed_vehicles * 3600.0 / observed_duration_seconds


def compute_station_metrics(
    results: list[TrackResult],
    station_name: str = "Demo Inspection Station",
    active_lanes: int = 3,
    observed_duration_seconds: float | None = None,
) -> StationMetrics:
    """Aggregate per-vehicle results into a :class:`StationMetrics` snapshot.

    Parameters
    ----------
    results:
        Per-vehicle :class:`TrackResult` list from the pipeline.
    station_name:
        Human-readable station name for display and the public card.
    active_lanes:
        Number of active inspection lanes (floored at 1). Until polygon-based
        lane assignment is implemented this is a station configuration value.
    observed_duration_seconds:
        Length of the observed window in seconds. When omitted it is inferred
        from the latest leave/enter time across all results.

    Notes
    -----
    - ``average_inspection_minutes`` / ``average_queue_wait_minutes`` are
      derived from completed vehicles (those with a known ``wait_time``).
      Until separate queue/bay zones exist, total station cycle time is used
      as the inspection-duration proxy; both fields share this value.
    - ``vehicles_in_queue`` is the peak concurrent count (queue-depth proxy).
    """
    lanes = max(1, active_lanes)
    total_vehicles = len(results)

    completed = [
        r for r in results if r.wait_time is not None and r.leave_time is not None
    ]
    completed_count = len(completed)

    if observed_duration_seconds is None:
        if results:
            observed_duration_seconds = max(
                (r.leave_time if r.leave_time is not None else r.enter_time)
                for r in results
            )
        else:
            observed_duration_seconds = 0.0

    queue_depth = peak_concurrent_vehicles(results)

    if completed:
        avg_wait_seconds = sum(r.wait_time for r in completed) / completed_count  # type: ignore[misc]
        avg_inspection_minutes = avg_wait_seconds / 60.0
        average_queue_wait_minutes = avg_inspection_minutes
    else:
        avg_inspection_minutes = None
        average_queue_wait_minutes = None

    throughput_per_hour = compute_throughput_per_hour(
        completed_count, observed_duration_seconds
    )

    if avg_inspection_minutes is not None and queue_depth > 0:
        raw_wait = estimate_public_wait(
            queue_depth, avg_inspection_minutes, lanes
        )
        estimated_public_wait_minutes: int | None = round_public_wait(raw_wait)
        status, status_label = classify_status(raw_wait)
    else:
        estimated_public_wait_minutes = None
        status, status_label = classify_status(None)

    return StationMetrics(
        station_name=station_name,
        total_vehicles=total_vehicles,
        vehicles_in_queue=queue_depth,
        completed_vehicles=completed_count,
        active_lanes=lanes,
        average_inspection_minutes=avg_inspection_minutes,
        average_queue_wait_minutes=average_queue_wait_minutes,
        estimated_public_wait_minutes=estimated_public_wait_minutes,
        throughput_per_hour=throughput_per_hour,
        observed_duration_minutes=observed_duration_seconds / 60.0,
        status=status,
        status_label=status_label,
    )
