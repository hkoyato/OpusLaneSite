"""Metrics (GET) handler for the Station_Stats_API.

This module implements the two read paths of the ``Metrics_Query_Endpoint``
(see design.md "Station_Stats_API — Metrics handler"):

- :func:`get_station` — single read for ``GET /stations/{station_id}``. It
  validates the ``Station_Identifier`` format (``400`` if malformed,
  Requirement 5.5), returns the current snapshot with ``200`` (Requirements 5.1,
  5.3), or ``404`` when no snapshot is stored for a well-formed station
  (Requirement 5.2).
- :func:`list_stations` — list read for ``GET /stations``. It returns ``200``
  with one ``{station_id, timestamp}`` entry for every station that has a stored
  snapshot, and an empty list when none do (Requirements 5.4, 5.6).

Both functions take an injected :class:`station_stats_api.store.StatisticsStore`
so the logic is exercised against the in-memory fake in tests without any AWS
calls. Neither function raises for a client error; an unexpected storage fault
is caught and surfaced as a generic ``503`` (Requirement 10.2), consistent with
the snapshot handler's approach. Each handled request emits exactly one guarded
log entry (Requirements 10.1, 10.5).
"""

from __future__ import annotations

from .http_result import (
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    HTTP_OK,
    HTTP_SERVICE_UNAVAILABLE,
    HttpResult,
)
from .logging_support import (
    REJECTION_MALFORMED_STATION_ID,
    REJECTION_NOT_FOUND,
    REJECTION_STORAGE_ERROR,
    build_log_entry,
    emit_log,
)
from .store import StatisticsStore
from .validation import is_valid_station_id

# Response-body messages for the metrics read paths. These mirror the bodies in
# design.md "Server-side error mapping" and carry no internal detail.
_MALFORMED_STATION_ID_MESSAGE = "malformed station identifier"
_NOT_FOUND_MESSAGE = "no statistics for station"
_STORAGE_ERROR_MESSAGE = "the request could not be completed"


def _emit(entry: dict, log_sink) -> None:
    """Emit ``entry`` through ``emit_log``, honoring an optional custom sink.

    ``emit_log`` is guarded: any failure in the sink is swallowed so logging
    never fails the request (Requirement 10.5).
    """
    if log_sink is None:
        emit_log(entry)
    else:
        emit_log(entry, log_sink)


def get_station(
    station_id: str,
    store: StatisticsStore,
    *,
    log_sink=None,
) -> HttpResult:
    """Return the current snapshot for ``station_id`` (single read).

    Validates the identifier format first: a malformed ``Station_Identifier``
    yields ``400`` without touching the store (Requirement 5.5). For a
    well-formed identifier, the store is queried: a present snapshot is returned
    with ``200`` and its full stored body preserving every field (Requirements
    5.1, 5.3); an absent snapshot yields ``404`` (Requirement 5.2). An
    unexpected storage fault is caught and returned as a generic ``503``
    (Requirement 10.2). Exactly one log entry is emitted (Requirement 10.1).

    Args:
        station_id: The requested ``Station_Identifier`` from the path.
        store: The :class:`StatisticsStore` to read from.
        log_sink: Optional log sink callable; the default sink is used when
            ``None``.

    Returns:
        An :class:`HttpResult` with status ``200``/``400``/``404``/``503``.
    """
    # Format check first — a malformed identifier never reaches the store.
    if not is_valid_station_id(station_id):
        result = HttpResult(HTTP_BAD_REQUEST, {"error": _MALFORMED_STATION_ID_MESSAGE})
        _emit(
            build_log_entry(
                station_id=station_id,
                http_status=result.status_code,
                rejection_category=REJECTION_MALFORMED_STATION_ID,
            ),
            log_sink,
        )
        return result

    try:
        snapshot = store.get(station_id)
    except Exception:  # noqa: BLE001 — surface unexpected storage faults as 503 (Req 10.2)
        result = HttpResult(HTTP_SERVICE_UNAVAILABLE, {"error": _STORAGE_ERROR_MESSAGE})
        _emit(
            build_log_entry(
                station_id=station_id,
                http_status=result.status_code,
                rejection_category=REJECTION_STORAGE_ERROR,
            ),
            log_sink,
        )
        return result

    if snapshot is None:
        result = HttpResult(HTTP_NOT_FOUND, {"error": _NOT_FOUND_MESSAGE})
        _emit(
            build_log_entry(
                station_id=station_id,
                http_status=result.status_code,
                rejection_category=REJECTION_NOT_FOUND,
            ),
            log_sink,
        )
        return result

    # Present: return the full stored snapshot, preserving all fields (Req 5.3).
    result = HttpResult(HTTP_OK, snapshot)
    _emit(
        build_log_entry(station_id=station_id, http_status=result.status_code),
        log_sink,
    )
    return result


def list_stations(
    store: StatisticsStore,
    *,
    log_sink=None,
) -> HttpResult:
    """Return ``{station_id, timestamp}`` for every stored station (list read).

    Returns ``200`` with one entry per station that has a stored snapshot, in
    the store's iteration order, and an empty list when no station has a
    snapshot (Requirements 5.4, 5.6). An unexpected storage fault is caught and
    returned as a generic ``503`` (Requirement 10.2). Exactly one log entry is
    emitted, with an explicit absent-identifier indicator since this resource
    carries no ``Station_Identifier`` (Requirement 10.1).

    Args:
        store: The :class:`StatisticsStore` to read the index from.
        log_sink: Optional log sink callable; the default sink is used when
            ``None``.

    Returns:
        An :class:`HttpResult` with status ``200`` (a possibly-empty list) or
        ``503``.
    """
    try:
        index = store.list_index()
    except Exception:  # noqa: BLE001 — surface unexpected storage faults as 503 (Req 10.2)
        result = HttpResult(HTTP_SERVICE_UNAVAILABLE, {"error": _STORAGE_ERROR_MESSAGE})
        _emit(
            build_log_entry(
                station_id=None,
                http_status=result.status_code,
                rejection_category=REJECTION_STORAGE_ERROR,
            ),
            log_sink,
        )
        return result

    body = [
        {"station_id": station_id, "timestamp": timestamp}
        for station_id, timestamp in index
    ]
    result = HttpResult(HTTP_OK, body)
    _emit(
        build_log_entry(station_id=None, http_status=result.status_code),
        log_sink,
    )
    return result
