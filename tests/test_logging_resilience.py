"""Unit tests for logging-failure resilience of the Station_Stats_API.

A logging failure must never fail a request: when the log sink raises, the
guarded :func:`emit_log` swallows the exception and reports failure, and any
handler that emits a log entry still returns its intended HTTP status. These
plain (non-Hypothesis) tests pin that guarantee with concrete examples.

Validates: Requirements 10.5
"""

from __future__ import annotations

from station_stats_api.http_result import HTTP_CREATED, HttpResult
from station_stats_api.logging_support import build_log_entry, emit_log


def _raising_sink(_entry: dict) -> None:
    """A log sink that always fails, simulating a broken logging backend."""
    raise RuntimeError("logging backend unavailable")


def test_emit_log_returns_false_when_sink_raises() -> None:
    """Req 10.5: a sink that raises is swallowed; emit_log returns False, no raise."""
    entry = build_log_entry(
        station_id="demo_station_01",
        http_status=HTTP_CREATED,
        request_timestamp="2026-06-12T13:45:00Z",
    )

    # The call must not propagate the sink's exception.
    result = emit_log(entry, sink=_raising_sink)

    assert result is False


def test_emit_log_returns_true_and_calls_sink_on_success() -> None:
    """On success emit_log returns True and hands the (redacted) entry to the sink."""
    captured: list[dict] = []

    def capturing_sink(redacted: dict) -> None:
        captured.append(redacted)

    entry = build_log_entry(
        station_id="demo_station_01",
        http_status=HTTP_CREATED,
        request_timestamp="2026-06-12T13:45:00Z",
    )

    result = emit_log(entry, sink=capturing_sink)

    assert result is True
    assert len(captured) == 1
    # The sink receives the (redacted) entry carrying the request's core fields.
    assert captured[0]["station_id"] == "demo_station_01"
    assert captured[0]["http_status"] == HTTP_CREATED
    assert captured[0]["request_timestamp"] == "2026-06-12T13:45:00Z"


def test_emit_log_redacts_credentials_before_handing_to_sink() -> None:
    """A failing sink never sees unredacted credential material either.

    Redaction happens inside the guarded emit, so even on the success path the
    sink only receives the redacted entry (Req 3.5/10.3 reinforced here for the
    resilience path).
    """
    captured: list[dict] = []
    entry = build_log_entry(
        station_id="demo_station_01",
        http_status=HTTP_CREATED,
        request_timestamp="2026-06-12T13:45:00Z",
    )
    entry["client_credential"] = "super-secret-key"

    assert emit_log(entry, sink=captured.append) is True
    assert captured[0]["client_credential"] == "<redacted>"


def _handler_like(*, status_code: int, log_sink) -> HttpResult:
    """A minimal handler-like function exercising the Req 10.5 guarantee.

    It builds its intended ``HttpResult`` status, emits a log entry through the
    provided (possibly failing) sink via the guarded :func:`emit_log`, and
    returns its intended status regardless of whether logging succeeded.
    """
    result = HttpResult(
        status_code=status_code,
        body={"station_id": "demo_station_01", "timestamp": "2026-06-12T13:45:00Z"},
    )

    entry = build_log_entry(
        station_id="demo_station_01",
        http_status=status_code,
        request_timestamp="2026-06-12T13:45:00Z",
    )
    # Guarded emit: a logging failure here must not change the returned status.
    emit_log(entry, sink=log_sink)

    return result


def test_handler_returns_intended_status_despite_logging_failure() -> None:
    """Req 10.5: a handler still returns its intended 201 when log emit raises."""
    result = _handler_like(status_code=HTTP_CREATED, log_sink=_raising_sink)

    assert result.status_code == HTTP_CREATED
    assert result.body["station_id"] == "demo_station_01"


def test_handler_status_matches_with_and_without_logging_failure() -> None:
    """The returned status is identical whether or not the log sink fails."""
    working_sink_calls: list[dict] = []

    ok_result = _handler_like(status_code=HTTP_CREATED, log_sink=working_sink_calls.append)
    failed_result = _handler_like(status_code=HTTP_CREATED, log_sink=_raising_sink)

    # Logging outcome differs (one sink recorded an entry, the other raised)...
    assert len(working_sink_calls) == 1
    # ...but the request's returned status is unchanged.
    assert ok_result.status_code == failed_result.status_code == HTTP_CREATED
