"""Guarded log-entry building and emission for the Station_Stats_API.

The Snapshot and Metrics handlers emit exactly one structured log entry per
handled request. This module implements that log-entry contract (Requirement
10.1) together with the secret/PII hygiene rules (Requirements 3.5, 10.3) and
the guarantee that a logging failure never fails the request (Requirement 10.5).

What this module provides:

- :func:`build_log_entry` — construct the single, complete log entry for a
  handled request: the ``station_id`` (or an explicit ``<absent>`` /
  ``<unparseable>`` indicator), the resulting HTTP status code, the request
  timestamp as an ISO 8601 date-time, and — only for a rejected request — a
  category describing the rejection reason (Requirement 10.1).
- :func:`redact` — defensively strip any sensitive value (``Client_Credential``,
  authorization/token material, and license-plate or driver-identifying data)
  from an entry before it is written (Requirements 3.5, 10.3).
- :func:`emit_log` — wrap the redaction + sink call so that any failure raised
  by the logging sink is swallowed and never propagates to the caller
  (Requirement 10.5).

The entry is a plain JSON-serializable ``dict`` so the default sink (and any
CloudWatch-backed sink in the Lambda adapter) can serialize it directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .validation import is_valid_station_id

# Module logger used by the default sink. The Lambda adapter may pass its own
# sink (e.g. one that writes to CloudWatch) instead.
_LOGGER = logging.getLogger("station_stats_api.requests")


# --- Station identifier indicators (Requirement 10.1) ---------------------------

#: Recorded when no Station_Identifier was present on the request at all.
STATION_ID_ABSENT = "<absent>"

#: Recorded when a Station_Identifier was present but could not be parsed as a
#: well-formed identifier.
STATION_ID_UNPARSEABLE = "<unparseable>"


# --- Rejection categories (Requirement 10.1) ------------------------------------
# A stable, log-only vocabulary describing *why* a request was rejected. These
# mirror the conditions in design.md "Server-side error mapping". They are
# recorded only for rejected requests (HTTP status >= 400).
REJECTION_MALFORMED_JSON = "malformed_json"
REJECTION_VALIDATION_FAILED = "validation_failed"
REJECTION_PAYLOAD_TOO_LARGE = "payload_too_large"
REJECTION_UNAUTHENTICATED = "unauthenticated"
REJECTION_FORBIDDEN = "forbidden"
REJECTION_METHOD_NOT_ALLOWED = "method_not_allowed"
REJECTION_MALFORMED_STATION_ID = "malformed_station_id"
REJECTION_NOT_FOUND = "not_found"
REJECTION_STORAGE_ERROR = "storage_error"
REJECTION_INTERNAL_ERROR = "internal_error"


# --- Redaction configuration (Requirements 3.5, 10.3) ---------------------------
# Any entry key whose lowercased name *contains* one of these substrings has its
# value replaced with the redaction placeholder. The list intentionally errs on
# the side of over-redaction: log entries never need to carry credentials,
# authorization material, license-plate text, or driver-identifying data.
_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "credential",
    "authorization",
    "auth_token",
    "api_key",
    "apikey",
    "x-api-key",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "plate",  # license-plate text
    "driver",  # driver-identifying data
    "owner",
)

#: Replacement value substituted for any redacted field.
REDACTED_PLACEHOLDER = "<redacted>"


def _resolve_station_indicator(station_id: object) -> str:
    """Resolve the value recorded for ``station_id`` in a log entry.

    Args:
        station_id: The raw identifier associated with the request. ``None``
            (or an empty value) means no identifier was present; a present but
            malformed value is treated as unparseable.

    Returns:
        The well-formed identifier string, or :data:`STATION_ID_ABSENT` /
        :data:`STATION_ID_UNPARSEABLE` (Requirement 10.1).
    """
    if station_id is None or station_id == "":
        return STATION_ID_ABSENT
    if is_valid_station_id(station_id):
        return station_id  # type: ignore[return-value]
    return STATION_ID_UNPARSEABLE


def build_log_entry(
    *,
    station_id: object,
    http_status: int,
    request_timestamp: str | None = None,
    rejection_category: str | None = None,
) -> dict:
    """Build the single log entry for one handled request (Requirement 10.1).

    The entry records the Station_Identifier (or an explicit indicator when it
    is absent or unparseable), the resulting HTTP status code, the request
    timestamp as an ISO 8601 date-time, and — only when the status denotes a
    rejection (>= 400) — a category describing the rejection reason.

    Args:
        station_id: The raw Station_Identifier for the request, or ``None`` when
            absent. Malformed values are recorded as ``<unparseable>``.
        http_status: The HTTP status code the handler is returning.
        request_timestamp: The request time as an ISO 8601 string. When omitted,
            the current UTC time is used.
        rejection_category: A category describing why the request was rejected.
            Recorded only for rejected requests (status >= 400); ignored for
            successful responses.

    Returns:
        A JSON-serializable ``dict`` with keys ``station_id``, ``http_status``,
        ``request_timestamp`` and, for rejected requests, ``rejection_category``.
    """
    if request_timestamp is None:
        request_timestamp = datetime.now(timezone.utc).isoformat()

    entry: dict = {
        "station_id": _resolve_station_indicator(station_id),
        "http_status": int(http_status),
        "request_timestamp": request_timestamp,
    }

    # A rejection category is recorded only for rejected requests (Req 10.1).
    if http_status >= 400:
        entry["rejection_category"] = (
            rejection_category
            if rejection_category is not None
            else REJECTION_INTERNAL_ERROR
        )

    return entry


def _is_sensitive_key(key: object) -> bool:
    """Return whether ``key`` names a field that must be redacted."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEY_SUBSTRINGS)


def redact(value: object) -> object:
    """Return a copy of ``value`` with sensitive fields redacted.

    Recursively walks dicts and lists. Any dict key whose name contains a known
    sensitive token (credential/authorization/token/secret/plate/driver, …) has
    its value replaced with :data:`REDACTED_PLACEHOLDER`. Other values are
    returned structurally unchanged. This guarantees a ``Client_Credential`` and
    any license-plate or driver-identifying data never reach a log sink
    (Requirements 3.5, 10.3).

    Args:
        value: A log entry (typically a ``dict``) or any nested JSON-like value.

    Returns:
        A redacted copy of ``value``. The input is not mutated.
    """
    if isinstance(value, dict):
        redacted: dict = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = REDACTED_PLACEHOLDER
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def _default_sink(entry: dict) -> None:
    """Default log sink: emit the redacted entry as a JSON line at INFO level."""
    _LOGGER.info(json.dumps(entry, default=str, sort_keys=True))


def emit_log(entry: dict, sink=_default_sink) -> bool:
    """Redact and emit ``entry`` through ``sink``, never failing the request.

    The entry is redacted (Requirements 3.5, 10.3) and handed to ``sink``. Any
    exception raised while redacting or emitting is swallowed so that a logging
    failure never propagates to — and therefore never fails — the request
    (Requirement 10.5).

    Args:
        entry: The log entry to emit, typically produced by
            :func:`build_log_entry`.
        sink: A callable that accepts the redacted entry ``dict`` and performs
            the actual write. Defaults to a JSON line at INFO level on the module
            logger.

    Returns:
        ``True`` if the entry was emitted successfully, ``False`` if emission
        failed (the failure is intentionally suppressed).
    """
    try:
        redacted = redact(entry)
        sink(redacted)
        return True
    except Exception:  # noqa: BLE001 — logging must never fail the request (Req 10.5)
        return False
