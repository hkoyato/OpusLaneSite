"""Shared HTTP result types and status-mapping constants for the Station Stats API.

This module defines the single value type that every request handler returns
(:class:`HttpResult`) along with the HTTP status-code constants and the
``PutOutcome`` -> HTTP status mapping used across the snapshot/metrics handlers
and the Lambda event adapter. Keeping these in one place lets the validator,
storage adapter, and handlers agree on response shapes without circular imports.

The ``HttpResult.body`` is always JSON-serializable so the Lambda proxy adapter
can hand it straight to ``json.dumps`` when shaping the API Gateway response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

# A JSON-serializable response body. The snapshot/metrics handlers only ever
# return objects (dict), lists, or ``None`` (no body), but the broad alias keeps
# the type honest for any JSON value an error body might carry.
JsonBody = Union[dict, list, str, int, float, bool, None]


# --- HTTP status-code constants -------------------------------------------------
# Centralized so handlers reference names instead of magic numbers. Each maps to
# a condition documented in design.md "Server-side error mapping".
HTTP_OK = 200  # successful GET / duplicate POST (Req 5.1, 8.8)
HTTP_CREATED = 201  # snapshot durably stored or accepted-but-not-current (Req 1.2)
HTTP_BAD_REQUEST = 400  # malformed JSON / malformed station_id (Req 2.5, 5.5)
HTTP_UNAUTHORIZED = 401  # missing credential (Req 3.2)
HTTP_FORBIDDEN = 403  # unknown/revoked credential (Req 3.3)
HTTP_NOT_FOUND = 404  # no stored snapshot for station (Req 5.2)
HTTP_METHOD_NOT_ALLOWED = 405  # wrong method on a resource (Req 1.5, 5.7)
HTTP_PAYLOAD_TOO_LARGE = 413  # body exceeds 16KB (Req 1.6)
HTTP_UNPROCESSABLE_ENTITY = 422  # validation failure (Req 2.6)
HTTP_INTERNAL_SERVER_ERROR = 500  # unexpected internal fault
HTTP_SERVICE_UNAVAILABLE = 503  # storage failure (Req 10.2)


# --- PutOutcome status mapping --------------------------------------------------
# The Statistics_Store reports one of these named outcomes for every write. The
# concrete ``PutOutcome`` enum is defined alongside the store adapter (task 3.1);
# this mapping is keyed by the outcome *name* so it can be shared without forcing
# an import cycle between this module and the store.
#
#   STORED            -> 201  the snapshot became the current snapshot
#   DUPLICATE         -> 200  same (station_id, timestamp) already stored (Req 8.8)
#   RETAINED_EXISTING -> 201  valid + accepted, but an older instant so it does
#                             not become current (Req 4.3); client treats it as
#                             published
PUT_OUTCOME_STATUS: dict[str, int] = {
    "STORED": HTTP_CREATED,
    "DUPLICATE": HTTP_OK,
    "RETAINED_EXISTING": HTTP_CREATED,
}


@dataclass(frozen=True)
class HttpResult:
    """The status code and JSON-serializable body returned by a request handler.

    Handlers never raise for client errors; they return an ``HttpResult`` with
    the appropriate status code. Only unexpected internal faults propagate and
    are mapped to a generic ``500`` by the Lambda adapter.

    Attributes:
        status_code: The HTTP status code to return.
        body: A JSON-serializable body, or ``None`` when the response has no body.
    """

    status_code: int
    body: JsonBody = None
