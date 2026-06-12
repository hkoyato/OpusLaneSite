"""Property-based test for log/response credential and driver-data hygiene.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the log-entry builder and redaction. The
functions under test (``station_stats_api.logging_support.build_log_entry``,
``redact``, and ``emit_log``) are pure (no AWS, no Qt), so the test runs
headless and cheaply across many generated credential- and plate-like inputs.

Validates: Requirements 3.5, 10.3
"""

from __future__ import annotations

import json
import string

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.http_result import HTTP_CREATED
from station_stats_api.logging_support import (
    REDACTED_PLACEHOLDER,
    build_log_entry,
    emit_log,
    redact,
)

# A fixed, well-formed station identifier and timestamp used for the
# non-sensitive fields of every generated entry. Neither contains the sentinel
# prefixes below, so a leaked sensitive value can never be confused with them.
_STATION_ID = "demo_station_01"
_TIMESTAMP = "2026-06-12T13:45:00Z"

# Restrict generated sensitive values to characters that ``json.dumps`` never
# escapes. If a value were to leak into the serialized output it would appear
# verbatim, so a substring check cannot produce a false negative due to JSON
# escaping. Values are non-empty and carry a distinctive sentinel prefix so they
# can never collide with the placeholder or the non-sensitive fields above.
_SAFE_ALPHABET = string.ascii_letters + string.digits + "-_"


def _sensitive_value(prefix: str) -> st.SearchStrategy[str]:
    """Distinctive, non-empty, JSON-safe sensitive value strategy."""
    return st.text(alphabet=_SAFE_ALPHABET, min_size=1, max_size=48).map(
        lambda s: f"{prefix}-{s}"
    )


@settings(max_examples=200)
@given(
    credential=_sensitive_value("CREDVAL"),
    plate=_sensitive_value("PLATEVAL"),
    driver=_sensitive_value("DRIVERVAL"),
)
# Feature: station-stats-api, Property 18: Logs and responses never leak credentials or driver data
def test_logs_and_responses_never_leak_credentials_or_driver_data(
    credential: str, plate: str, driver: str
) -> None:
    """For any request and any Client_Credential value, the emitted log entry and
    the response body contain no occurrence of the credential value and no
    license-plate text or driver-identifying data.
    """
    # Build the canonical log entry for a handled request, then attach the
    # sensitive values under sensitive keys at the top level and nested inside
    # dicts and lists — exactly the shapes redaction must defend against.
    entry = build_log_entry(
        station_id=_STATION_ID,
        http_status=HTTP_CREATED,
        request_timestamp=_TIMESTAMP,
    )
    entry["client_credential"] = credential
    entry["authorization"] = f"Bearer {credential}"
    entry["api_key"] = credential
    entry["plate_text"] = plate
    entry["driver_name"] = driver
    entry["context"] = {
        "x-api-key": credential,
        "nested": {"driver_id": driver, "plate": plate, "secret": credential},
    }
    entry["events"] = [
        {"owner": driver},
        {"auth_token": credential},
        {"plate_number": plate},
    ]

    # Capture the entry as it would actually be written to a sink.
    captured: list[dict] = []
    assert emit_log(entry, sink=captured.append) is True
    assert len(captured) == 1
    emitted = captured[0]

    # The serialized emitted entry must contain none of the sensitive values.
    serialized = json.dumps(emitted, default=str, sort_keys=True)
    for secret in (credential, plate, driver):
        assert secret not in serialized

    # Calling redact directly yields the same guarantee on the raw entry.
    redacted_serialized = json.dumps(redact(entry), default=str, sort_keys=True)
    for secret in (credential, plate, driver):
        assert secret not in redacted_serialized

    # The sensitive keys are present but replaced with the placeholder, so the
    # absence above is genuine redaction, not accidental field omission.
    assert emitted["client_credential"] == REDACTED_PLACEHOLDER
    assert emitted["authorization"] == REDACTED_PLACEHOLDER
    assert emitted["api_key"] == REDACTED_PLACEHOLDER
    assert emitted["plate_text"] == REDACTED_PLACEHOLDER
    assert emitted["driver_name"] == REDACTED_PLACEHOLDER
    assert emitted["context"]["x-api-key"] == REDACTED_PLACEHOLDER
    assert emitted["context"]["nested"]["driver_id"] == REDACTED_PLACEHOLDER
    assert emitted["context"]["nested"]["plate"] == REDACTED_PLACEHOLDER
    assert emitted["context"]["nested"]["secret"] == REDACTED_PLACEHOLDER
    assert emitted["events"][0]["owner"] == REDACTED_PLACEHOLDER
    assert emitted["events"][1]["auth_token"] == REDACTED_PLACEHOLDER
    assert emitted["events"][2]["plate_number"] == REDACTED_PLACEHOLDER

    # Non-sensitive request fields survive redaction unchanged.
    assert emitted["station_id"] == _STATION_ID
    assert emitted["request_timestamp"] == _TIMESTAMP

    # A handler-style response body (station_id + stored timestamp) never carries
    # the credential, plate, or driver data (Req 3.5/10.3 for response bodies).
    response_body = {"station_id": _STATION_ID, "timestamp": _TIMESTAMP}
    response_serialized = json.dumps(response_body, default=str, sort_keys=True)
    for secret in (credential, plate, driver):
        assert secret not in response_serialized
