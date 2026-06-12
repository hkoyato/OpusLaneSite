"""Record producers for station-attributed data (Qt-free, pure functions).

These helpers build the data-model records described in ``product_overview``
§11 (Vehicle_Session, Zone_Event, Station_Metric_Snapshot), each carrying the
active ``station_id`` captured **by value** at the moment the record is created
(Requirement 5).

Design contract:
  - The ``station_id`` is a plain ``str`` copied into the returned dict, so a
    later change to the active StationConfig cannot mutate an already-created
    record (Req 5.5).
  - The producers are pure and Qt-free so they are unit- and property-testable
    in isolation. Callers obtain the snapshot identifier from
    ``StationController.active_identifier()`` and pass it in directly.
  - Input field dicts are never mutated; a shallow copy is taken before the
    ``station_id`` is set (Req 5.1-5.4).
"""

from __future__ import annotations

from typing import Callable

__all__ = [
    "build_vehicle_session",
    "build_zone_event",
    "build_station_metric_snapshot",
    "capture_active_identifier",
]


def _with_station_id(fields: dict, station_id: str) -> dict:
    """Return a shallow copy of ``fields`` with ``station_id`` set by value.

    The input dict is copied (never mutated) and the ``station_id`` key is
    overwritten with the captured identifier string (Req 5.4, 5.5).
    """
    record = dict(fields)
    record["station_id"] = station_id
    return record


def build_vehicle_session(session_fields: dict, station_id: str) -> dict:
    """Return a Vehicle_Session record with ``station_id`` captured by value.

    Merges ``session_fields`` and sets ``station_id`` to the active identifier
    captured at creation. ``session_fields`` is not mutated (Req 5.1, 5.4, 5.5).
    """
    return _with_station_id(session_fields, station_id)


def build_zone_event(event_fields: dict, station_id: str) -> dict:
    """Return a Zone_Event record with ``station_id`` captured by value.

    Merges ``event_fields`` and sets ``station_id`` to the active identifier
    captured at creation. ``event_fields`` is not mutated (Req 5.2, 5.4, 5.5).
    """
    return _with_station_id(event_fields, station_id)


def build_station_metric_snapshot(metric_fields: dict, station_id: str) -> dict:
    """Return a Station_Metric_Snapshot with ``station_id`` captured by value.

    Merges ``metric_fields`` and sets ``station_id`` to the active identifier
    captured at creation. ``metric_fields`` is not mutated (Req 5.3, 5.4, 5.5).
    """
    return _with_station_id(metric_fields, station_id)


def capture_active_identifier(provider: Callable[[], str]) -> str:
    """Return the active identifier by invoking ``provider`` at call time.

    Makes the "capture at creation" step explicit: callers pass
    ``StationController.active_identifier`` so the snapshot is taken at the
    moment the record is built (Req 5.4, 5.5).
    """
    return provider()
