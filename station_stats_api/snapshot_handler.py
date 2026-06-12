"""Snapshot (POST) handler for the Station_Stats_API.

This module implements :func:`handle_snapshot`, the internal handler contract
behind the ``Snapshot_Endpoint`` (``POST /stations/{station_id}/snapshot``). It
turns a raw request body into a deterministic :class:`HttpResult`, applying the
parse -> validate -> strip -> store pipeline described in design.md
("Station_Stats_API — Snapshot handler") and the "Server-side error mapping"
table.

Behavior (Requirements 1.2, 1.4, 2.5, 2.6, 2.7, 8.8, 10.2):

1. Parse ``raw_body`` as JSON. On a parse failure respond ``400`` with a
   malformed-JSON body and store nothing (Req 2.5).
2. Validate the parsed object with :func:`validate_snapshot`. On failure respond
   ``422`` naming each failing field and store nothing (Req 2.6).
3. On success, ``cleaned`` already contains only the Glossary-defined fields, so
   any extra keys are stripped before storage (Req 2.7).
4. Call :meth:`StatisticsStore.put_if_newer` and map the outcome to an HTTP
   status: ``STORED``/``RETAINED_EXISTING`` -> ``201``, ``DUPLICATE`` -> ``200``
   (Req 1.2, 8.8). The accepted/duplicate body carries the ``station_id`` and the
   stored ``timestamp`` (Req 1.4).
5. If the store raises, respond ``503`` with a generic body that carries no
   internal detail and leaves no partial record (Req 10.2, 10.4).

The handler never raises for a client error; every outcome is a returned
:class:`HttpResult`. Exactly one structured log entry is emitted per request via
:func:`emit_log`, which is guarded so a logging failure never fails the request
(Req 10.1, 10.5). A ``log_sink`` may be injected for tests.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from .http_result import (
    HTTP_BAD_REQUEST,
    HTTP_PAYLOAD_TOO_LARGE,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_UNPROCESSABLE_ENTITY,
    HttpResult,
)
from .logging_support import (
    REJECTION_MALFORMED_JSON,
    REJECTION_PAYLOAD_TOO_LARGE,
    REJECTION_STORAGE_ERROR,
    REJECTION_VALIDATION_FAILED,
    build_log_entry,
    emit_log,
)
from .store import StatisticsStore
from .validation import validate_snapshot

#: Maximum accepted request body size in bytes: 16 kilobytes (Req 1.1, 1.6).
#: API Gateway enforces this at the edge, and the handler enforces it again as
#: defense in depth so the Lambda never validates or stores an oversize body.
MAX_BODY_BYTES = 16 * 1024

#: Generic message body for malformed-JSON rejections (Req 2.5).
_MALFORMED_JSON_BODY = {"error": "malformed JSON"}

#: Body for an oversize request. Identifies the request as exceeding the maximum
#: allowed body size (Req 1.6).
_PAYLOAD_TOO_LARGE_BODY = {
    "error": "request exceeds maximum allowed body size of 16384 bytes"
}

#: Generic message body for a storage failure. Carries no internal detail
#: (no stack trace, internal code, or implementation detail) per Req 10.2/10.4.
_STORAGE_ERROR_BODY = {"error": "the request could not be completed"}


def _parse_json(raw_body: bytes) -> object:
    """Parse ``raw_body`` as JSON, returning the decoded object.

    Accepts ``bytes`` or ``str``. Raises :class:`ValueError` (the base class of
    :class:`json.JSONDecodeError`) for any body that is not decodable UTF-8 or
    not valid JSON, so the caller can map every parse failure to ``400``.
    """
    if isinstance(raw_body, (bytes, bytearray)):
        # A non-UTF-8 body is just as malformed as invalid JSON; surface it as a
        # ValueError so the single 400 path handles both (Req 2.5).
        try:
            text = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("body is not valid UTF-8") from exc
    else:
        text = raw_body
    return json.loads(text)


def handle_snapshot(
    raw_body: bytes,
    store: StatisticsStore,
    *,
    station_path_id: Optional[str] = None,
    log_sink: Optional[Callable[[dict], None]] = None,
) -> HttpResult:
    """Validate and store one snapshot, returning a deterministic result.

    Args:
        raw_body: The raw request body (``bytes`` or ``str``) containing a single
            JSON-encoded ``Station_Metric_Snapshot``.
        store: The :class:`StatisticsStore` used to persist the snapshot. Injected
            so handlers and tests can use the in-memory fake or the DynamoDB
            adapter interchangeably.
        station_path_id: The ``station_id`` carried in the request path, if any.
            It is used only as the logged identifier when the body cannot be
            parsed; the stored record always uses the validated body's
            ``station_id`` (design.md note on the handler contract).
        log_sink: Optional callable receiving the redacted log entry. Defaults to
            the module log sink. Injected for tests.

    Returns:
        An :class:`HttpResult`:
        - ``413`` with a max-body-size body when the body exceeds 16 kilobytes.
        - ``400`` with a malformed-JSON body when the body is not valid JSON.
        - ``422`` naming each failing field when validation fails.
        - ``201`` (stored / retained) or ``200`` (duplicate) with a
          ``{"station_id", "timestamp"}`` body on a valid, accepted snapshot.
        - ``503`` with a generic body when the store raises a storage error.
    """
    # --- 0. Enforce the 16KB body-size limit (Req 1.6) --------------------------
    # Measured against the raw byte length so a str body is sized by its UTF-8
    # encoding, matching what the gateway counts. An oversize body is rejected
    # before any parse/validate/store work, so nothing is ever stored.
    if isinstance(raw_body, str):
        body_size = len(raw_body.encode("utf-8"))
    else:
        body_size = len(raw_body)
    if body_size > MAX_BODY_BYTES:
        return _finish(
            HttpResult(HTTP_PAYLOAD_TOO_LARGE, dict(_PAYLOAD_TOO_LARGE_BODY)),
            station_id=station_path_id,
            rejection_category=REJECTION_PAYLOAD_TOO_LARGE,
            log_sink=log_sink,
        )

    # --- 1. Parse JSON (Req 2.5) ------------------------------------------------
    try:
        parsed = _parse_json(raw_body)
    except ValueError:
        # Malformed JSON (or non-UTF-8 body): nothing stored, log the category.
        return _finish(
            HttpResult(HTTP_BAD_REQUEST, dict(_MALFORMED_JSON_BODY)),
            station_id=station_path_id,
            rejection_category=REJECTION_MALFORMED_JSON,
            log_sink=log_sink,
        )

    # --- 2. Validate (Req 2.6) --------------------------------------------------
    result = validate_snapshot(parsed)
    if not result.is_valid:
        # Name exactly the failing fields; store nothing (Req 2.6).
        logged_station_id = (
            parsed.get("station_id") if isinstance(parsed, dict) else None
        )
        return _finish(
            HttpResult(
                HTTP_UNPROCESSABLE_ENTITY,
                {
                    "error": "validation failed",
                    "failing_fields": list(result.failing_fields),
                },
            ),
            station_id=logged_station_id,
            rejection_category=REJECTION_VALIDATION_FAILED,
            log_sink=log_sink,
        )

    # cleaned holds exactly the Glossary fields — extra keys already stripped (Req 2.7).
    cleaned = result.cleaned
    assert cleaned is not None  # guaranteed when is_valid

    # --- 3. Store with last-write-wins (Req 1.2, 8.8) ---------------------------
    try:
        outcome = store.put_if_newer(cleaned)
    except Exception:  # noqa: BLE001 — any storage fault maps to a generic 503 (Req 10.2)
        # The store is atomic, so no partial record remains. The generic body
        # carries no internal detail (Req 10.2, 10.4).
        return _finish(
            HttpResult(HTTP_SERVICE_UNAVAILABLE, dict(_STORAGE_ERROR_BODY)),
            station_id=cleaned["station_id"],
            rejection_category=REJECTION_STORAGE_ERROR,
            log_sink=log_sink,
        )

    # --- 4. Map the accepted/duplicate outcome to a response (Req 1.4) ----------
    status = outcome.http_status
    body = {
        "station_id": cleaned["station_id"],
        "timestamp": cleaned["timestamp"],
    }
    return _finish(
        HttpResult(status, body),
        station_id=cleaned["station_id"],
        rejection_category=None,
        log_sink=log_sink,
    )


def _finish(
    result: HttpResult,
    *,
    station_id: object,
    rejection_category: Optional[str],
    log_sink: Optional[Callable[[dict], None]],
) -> HttpResult:
    """Emit exactly one log entry for the request and return ``result``.

    Building and emitting the log entry is guarded by :func:`emit_log`, so a
    logging failure never changes the returned status (Req 10.1, 10.5).
    """
    entry = build_log_entry(
        station_id=station_id,
        http_status=result.status_code,
        rejection_category=rejection_category,
    )
    if log_sink is None:
        emit_log(entry)
    else:
        emit_log(entry, log_sink)
    return result
