"""AWS Lambda event adapter for the Station_Stats_API.

This module is the thin glue between API Gateway proxy events and the pure
request handlers (:func:`handle_snapshot`, :func:`get_station`,
:func:`list_stations`). It is the code referenced by ``infra/template.yaml`` at
``station_stats_api.lambda_handler.snapshot_handler`` /
``...metrics_handler`` / ``...authorizer_handler`` (see design.md
"Wire the API Gateway and Lambda entry points", task 8.2).

Responsibilities
----------------
1. Translate an API Gateway proxy event (``httpMethod``, ``resource``/``path``,
   ``pathParameters``, ``body``, ``isBase64Encoded``) into the correct internal
   handler call and translate the returned :class:`HttpResult` back into an API
   Gateway proxy response (Req 1.2, 5.1, 5.4).
2. Lazily construct a single default :class:`DynamoStatisticsStore` from the
   ``STATISTICS_TABLE_NAME`` environment variable on first use. The store (and
   therefore ``boto3``) is **never** built at import time, so importing this
   module needs no AWS credentials or ``boto3`` install. A store may be injected
   for tests.
3. Provide a minimal credential authorizer that reads the ``X-Client-Credential``
   header: a missing credential raises ``Unauthorized`` (API Gateway -> ``401``),
   an unknown/revoked credential yields an IAM ``Deny`` policy (-> ``403``), and a
   recognized credential yields an ``Allow`` policy. The credential value is
   never logged (Req 3.5).
4. Map any unexpected exception in the proxy handlers to a generic ``500``
   response that carries no internal detail (Req 10.4).

Routing
-------
- ``POST /stations/{station_id}/snapshot`` -> :func:`handle_snapshot`
- ``GET  /stations/{station_id}``          -> :func:`get_station`
- ``GET  /stations``                       -> :func:`list_stations`

The metrics resources share one Lambda (:func:`metrics_handler`) that routes
between the single-station read and the list read based on whether a
``station_id`` path parameter is present.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Iterable, Optional

from .dynamo_store import DEFAULT_TABLE_NAME, DynamoStatisticsStore
from .http_result import HTTP_INTERNAL_SERVER_ERROR, HttpResult
from .metrics_handler import get_station, list_stations
from .snapshot_handler import handle_snapshot
from .store import StatisticsStore

# --- Configuration --------------------------------------------------------------

#: Environment variable naming the DynamoDB table that backs the Statistics_Store.
#: Mirrors the ``STATISTICS_TABLE_NAME`` set in ``infra/template.yaml`` Globals.
TABLE_NAME_ENV_VAR = "STATISTICS_TABLE_NAME"

#: Header carrying the Client_Credential, matching the API Gateway authorizer
#: identity source in ``infra/template.yaml``. Looked up case-insensitively.
CREDENTIAL_HEADER = "X-Client-Credential"

#: Environment variable holding the comma-separated set of recognized
#: Client_Credentials for the authorizer.
CREDENTIAL_ENV_VAR = "STATION_STATS_CLIENT_CREDENTIALS"

#: Placeholder prototype credential set used only when ``CREDENTIAL_ENV_VAR`` is
#: not configured. This is a stand-in for a real credential store (e.g. Secrets
#: Manager / SSM) and exists so the hackathon prototype is demoable end-to-end.
PLACEHOLDER_CREDENTIALS: frozenset[str] = frozenset({"lanesight-demo-credential"})

#: Generic body for unexpected internal faults — no stack traces, internal
#: codes, or implementation detail (Req 10.4).
_INTERNAL_ERROR_BODY = {"error": "The request could not be completed."}

#: JSON content type returned on every proxy response.
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Client-Credential",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


# --- Lazy default store singleton -----------------------------------------------
# Built on first use, never at import, so importing this module makes no AWS call
# and does not require boto3 to be installed.
_default_store: Optional[StatisticsStore] = None


def _get_default_store() -> StatisticsStore:
    """Return the process-wide default :class:`DynamoStatisticsStore`.

    Constructs the store from the ``STATISTICS_TABLE_NAME`` environment variable
    on first call and caches it for subsequent invocations (the warm-Lambda
    reuse pattern). ``boto3`` is imported lazily inside the store, so this is the
    first point at which AWS access is required.
    """
    global _default_store
    if _default_store is None:
        table_name = os.environ.get(TABLE_NAME_ENV_VAR, DEFAULT_TABLE_NAME)
        _default_store = DynamoStatisticsStore(table_name=table_name)
    return _default_store


# --- Event/response translation -------------------------------------------------


def _extract_body(event: dict) -> bytes:
    """Return the request body as ``bytes``, decoding base64 when flagged.

    API Gateway delivers the body as a string and sets ``isBase64Encoded`` to
    ``True`` for binary or compressed payloads. A missing body becomes empty
    bytes so the JSON parse in :func:`handle_snapshot` yields a clean ``400``.
    """
    raw = event.get("body")
    if raw is None:
        return b""
    if event.get("isBase64Encoded"):
        # raw is a base64 string; decode to the original bytes.
        return base64.b64decode(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    # Already bytes-like (some test harnesses pass bytes directly).
    return bytes(raw)


def _to_proxy_response(result: HttpResult) -> dict:
    """Convert an :class:`HttpResult` into an API Gateway proxy response dict.

    The body is JSON-serialized when present, or an empty string when the result
    carries no body.
    """
    body = "" if result.body is None else json.dumps(result.body)
    return {
        "statusCode": result.status_code,
        "headers": dict(_JSON_HEADERS),
        "body": body,
    }


def _internal_error_response() -> dict:
    """Return the generic ``500`` proxy response for an unexpected fault (Req 10.4)."""
    return {
        "statusCode": HTTP_INTERNAL_SERVER_ERROR,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(_INTERNAL_ERROR_BODY),
    }


def _method_not_allowed_response() -> dict:
    """Return a ``405`` proxy response for an unexpected HTTP method (Req 1.5, 5.7).

    Defense-in-depth: API Gateway enforces method routing via the DEFAULT_4XX
    GatewayResponse so these methods never reach the Lambda in normal
    operation. This guard ensures correct behavior when the handler is invoked
    directly (tests, local dev, or misconfigured gateway).
    """
    return {
        "statusCode": 405,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps({"error": "Method not allowed."}),
    }


def _cors_preflight_response() -> dict:
    """Return a ``200`` response for OPTIONS preflight requests (CORS)."""
    return {
        "statusCode": 200,
        "headers": dict(_JSON_HEADERS),
        "body": "",
    }


def _path_parameters(event: dict) -> dict:
    """Return the event's ``pathParameters`` as a dict (never ``None``)."""
    return event.get("pathParameters") or {}


# --- Lambda entry points (referenced by infra/template.yaml) --------------------


def snapshot_handler(
    event: dict,
    context: Any = None,
    *,
    store: Optional[StatisticsStore] = None,
    log_sink: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Entry point for ``POST /stations/{station_id}/snapshot``.

    Translates the proxy event into a :func:`handle_snapshot` call and the result
    back into a proxy response. Any unexpected fault (including a failure to build
    the default store) maps to a generic ``500`` (Req 10.4).

    Defense-in-depth: rejects any HTTP method other than POST with ``405``
    (Req 1.5). API Gateway already enforces this via the ``DEFAULT_4XX``
    GatewayResponse, but the handler validates as well so that if it is ever
    invoked outside the gateway context (tests, direct invocation) it still
    behaves correctly.

    Args:
        event: The API Gateway proxy event.
        context: The Lambda context (unused).
        store: Optional injected :class:`StatisticsStore` for tests; defaults to
            the lazily-built DynamoDB store.
        log_sink: Optional log sink forwarded to the handler for tests.

    Returns:
        An API Gateway proxy response dict.
    """
    try:
        method = (event.get("httpMethod") or "").upper()
        if method == "OPTIONS":
            return _cors_preflight_response()
        if method != "POST":
            return _method_not_allowed_response()
        active_store = store if store is not None else _get_default_store()
        station_path_id = _path_parameters(event).get("station_id")
        body = _extract_body(event)
        result = handle_snapshot(
            body,
            active_store,
            station_path_id=station_path_id,
            log_sink=log_sink,
        )
        return _to_proxy_response(result)
    except Exception:  # noqa: BLE001 — unexpected faults become a generic 500 (Req 10.4)
        return _internal_error_response()


def metrics_handler(
    event: dict,
    context: Any = None,
    *,
    store: Optional[StatisticsStore] = None,
    log_sink: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Entry point for ``GET /stations`` and ``GET /stations/{station_id}``.

    Routes to :func:`get_station` when a ``station_id`` path parameter is present
    and to :func:`list_stations` otherwise, then translates the result into a
    proxy response. Any unexpected fault maps to a generic ``500`` (Req 10.4).

    Defense-in-depth: rejects any HTTP method other than GET with ``405``
    (Req 5.7). API Gateway already enforces this via the ``DEFAULT_4XX``
    GatewayResponse, but the handler validates as well so that if it is ever
    invoked outside the gateway context (tests, direct invocation) it still
    behaves correctly.

    Args:
        event: The API Gateway proxy event.
        context: The Lambda context (unused).
        store: Optional injected :class:`StatisticsStore` for tests; defaults to
            the lazily-built DynamoDB store.
        log_sink: Optional log sink forwarded to the handler for tests.

    Returns:
        An API Gateway proxy response dict.
    """
    try:
        method = (event.get("httpMethod") or "").upper()
        if method == "OPTIONS":
            return _cors_preflight_response()
        if method != "GET":
            return _method_not_allowed_response()
        active_store = store if store is not None else _get_default_store()
        station_id = _path_parameters(event).get("station_id")
        if station_id is not None:
            result = get_station(station_id, active_store, log_sink=log_sink)
        else:
            result = list_stations(active_store, log_sink=log_sink)
        return _to_proxy_response(result)
    except Exception:  # noqa: BLE001 — unexpected faults become a generic 500 (Req 10.4)
        return _internal_error_response()


# --- Credential authorizer ------------------------------------------------------


def _header_value(event: dict, name: str) -> Optional[str]:
    """Return the value of header ``name`` from ``event``, matched case-insensitively."""
    headers = event.get("headers") or {}
    target = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == target:
            return value
    return None


def _recognized_credentials() -> frozenset[str]:
    """Return the set of recognized Client_Credentials.

    Reads ``STATION_STATS_CLIENT_CREDENTIALS`` (a comma-separated list) when
    configured; otherwise falls back to :data:`PLACEHOLDER_CREDENTIALS`. This is
    a placeholder for the prototype — a production deployment would resolve
    credentials from a managed secret store.
    """
    raw = os.environ.get(CREDENTIAL_ENV_VAR)
    if not raw:
        return PLACEHOLDER_CREDENTIALS
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _generate_policy(effect: str, resource: str) -> dict:
    """Build an IAM policy document granting or denying ``execute-api:Invoke``.

    The ``principalId`` is a generic, non-sensitive identifier — the credential
    value is never placed in the policy or logged (Req 3.5).
    """
    return {
        "principalId": "lanesight-client",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }


def authorizer_handler(
    event: dict,
    context: Any = None,
    *,
    recognized_credentials: Optional[Iterable[str]] = None,
) -> dict:
    """API Gateway REQUEST authorizer enforcing the Client_Credential (Req 3.1–3.3).

    Behavior:
    - Missing credential -> raise ``Unauthorized``. API Gateway maps this exact
      message to an HTTP ``401`` via the ``UNAUTHORIZED`` GatewayResponse.
    - Unknown/revoked credential -> return an IAM ``Deny`` policy, which API
      Gateway surfaces as HTTP ``403`` via the ``ACCESS_DENIED`` GatewayResponse.
    - Recognized credential -> return an IAM ``Allow`` policy.

    The credential value is never logged or echoed (Req 3.5).

    Args:
        event: The API Gateway REQUEST authorizer event. ``methodArn`` (or
            ``routeArn``) identifies the protected resource.
        context: The Lambda context (unused).
        recognized_credentials: Optional injected set of recognized credentials
            for tests; defaults to :func:`_recognized_credentials`.

    Returns:
        An IAM policy document (Allow or Deny).

    Raises:
        Exception: With the message ``"Unauthorized"`` when no credential is
            present, so API Gateway returns ``401``.
    """
    credential = _header_value(event, CREDENTIAL_HEADER)
    if not credential:
        # API Gateway requires the literal "Unauthorized" to produce a 401.
        raise Exception("Unauthorized")

    allowed = (
        frozenset(recognized_credentials)
        if recognized_credentials is not None
        else _recognized_credentials()
    )
    # methodArn scopes the policy to the invoked method; fall back to a wildcard
    # if the event shape omits it.
    resource = event.get("methodArn") or event.get("routeArn") or "*"

    effect = "Allow" if credential in allowed else "Deny"
    return _generate_policy(effect, resource)
