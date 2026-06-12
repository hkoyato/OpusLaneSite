"""Station_Metric_Snapshot validation for the Station_Stats_API.

This module implements the validation rules of Requirement 2 (and the shared
``station_id`` format rule reused by the GET path, Requirement 5.5). It exposes:

- :func:`is_valid_station_id` — the reusable ``station_id``/``slowest_lane_id``
  format check (1–64 chars, ``[a-z0-9_-]`` only). The Metrics handler reuses this
  to reject a malformed ``Station_Identifier`` on GET (Requirement 5.5).
- :class:`ValidationResult` — the immutable outcome of validating a candidate
  snapshot. It drives the ``422`` field-naming response and is the unit under the
  Property 3 / Property 4 property tests.
- :func:`validate_snapshot` — validate a parsed object against the
  ``Station_Metric_Snapshot`` rules, returning the failing fields and, when valid,
  a ``cleaned`` dict containing only the Glossary-defined fields.

Validation operates on an already-parsed object (a ``dict``). JSON parsing and the
``400`` malformed-JSON response are the responsibility of the snapshot handler
(task 4.1); a non-dict input here is reported via :func:`validate_snapshot` as a
fully-failing snapshot.

Note on booleans: in Python ``bool`` is a subclass of ``int``. A boolean is never
a valid numeric value for any integer or number field, so booleans are rejected
explicitly (e.g. ``True`` is not an acceptable ``vehicles_in_queue``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .timestamps import is_valid_timestamp

# --- Field groups (from the data model, design.md) ------------------------------

#: Integer fields constrained to [0, 1_000_000] (Requirement 2.2).
INTEGER_FIELDS: tuple[str, ...] = (
    "vehicles_in_queue",
    "vehicles_in_bay",
    "active_lanes",
    "throughput_per_hour",
)

#: "Minute" number fields constrained to [0, 100_000] (Requirement 2.3).
MINUTE_FIELDS: tuple[str, ...] = (
    "average_queue_wait_minutes",
    "average_inspection_minutes",
    "estimated_public_wait_minutes",
)

#: The complete set of Glossary-defined snapshot fields, in canonical order.
GLOSSARY_FIELDS: tuple[str, ...] = (
    "station_id",
    "timestamp",
    "vehicles_in_queue",
    "vehicles_in_bay",
    "active_lanes",
    "average_queue_wait_minutes",
    "average_inspection_minutes",
    "estimated_public_wait_minutes",
    "throughput_per_hour",
    "slowest_lane_id",
    "confidence_score",
)

#: Bounds for the integer fields (inclusive).
_INTEGER_MIN = 0
_INTEGER_MAX = 1_000_000

#: Bounds for the minute fields (inclusive).
_MINUTE_MIN = 0
_MINUTE_MAX = 100_000

#: Bounds for confidence_score (inclusive).
_CONFIDENCE_MIN = 0
_CONFIDENCE_MAX = 1

#: ``station_id`` / ``slowest_lane_id`` format: 1–64 of lowercase letters,
#: digits, hyphens, and underscores (Requirements 2.1, 2.8, 5.5).
_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


def is_valid_station_id(value: object) -> bool:
    """Return whether ``value`` is a well-formed station identifier.

    A valid identifier is a non-empty string of 1 to 64 characters containing
    only lowercase letters, digits, hyphens, and underscores. This is the rule
    shared by ``station_id`` (Requirement 2.1) and the GET-path
    ``Station_Identifier`` format check (Requirement 5.5); ``slowest_lane_id``
    uses the same character/length rule when non-null (Requirement 2.8).

    Args:
        value: A candidate identifier of any type.

    Returns:
        ``True`` if ``value`` is a string matching ``[a-z0-9_-]{1,64}``,
        ``False`` otherwise.
    """
    return isinstance(value, str) and _ID_PATTERN.match(value) is not None


def _is_real_number(value: object) -> bool:
    """Return whether ``value`` is a real number, excluding ``bool``.

    ``bool`` is a subclass of ``int`` in Python and must never satisfy a numeric
    field constraint, so it is rejected here.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: object) -> bool:
    """Return whether ``value`` is an integer, excluding ``bool``."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class ValidationResult:
    """The immutable outcome of validating a candidate snapshot.

    Attributes:
        is_valid: ``True`` iff every Glossary field satisfies its rule.
        cleaned: When ``is_valid``, a dict containing only the Glossary-defined
            fields (extra keys stripped); ``None`` when invalid.
        failing_fields: The names of the fields that violated a rule. Empty iff
            ``is_valid``. A field is listed once regardless of how many rules it
            breaks.
    """

    is_valid: bool
    cleaned: dict | None
    failing_fields: list[str]


def validate_snapshot(obj: object) -> ValidationResult:
    """Validate a parsed snapshot object against the Requirement 2 rules.

    Every Glossary field except ``slowest_lane_id`` is required and non-null;
    ``slowest_lane_id`` may be ``null`` or a well-formed identifier. Field values
    must satisfy the type and range rules of the data model. Extra keys beyond the
    Glossary are ignored for validation and stripped from ``cleaned``
    (Requirement 2.7).

    Args:
        obj: The already-parsed request payload. Expected to be a ``dict``; any
            other type is reported as a fully-failing snapshot (all required
            fields missing).

    Returns:
        A :class:`ValidationResult`. When valid, ``cleaned`` holds exactly the
        Glossary fields and ``failing_fields`` is empty. When invalid,
        ``cleaned`` is ``None`` and ``failing_fields`` names exactly the
        violating fields (Requirement 2.6).
    """
    if not isinstance(obj, dict):
        # A non-object payload cannot carry any required field; report them all
        # as failing (slowest_lane_id is optional, so it is not listed).
        return ValidationResult(
            is_valid=False,
            cleaned=None,
            failing_fields=[f for f in GLOSSARY_FIELDS if f != "slowest_lane_id"],
        )

    failing: list[str] = []

    # station_id: required, non-null, 1–64 [a-z0-9_-] (Req 2.1).
    if not is_valid_station_id(obj.get("station_id")):
        failing.append("station_id")

    # timestamp: required, non-null, ISO 8601 with explicit offset or 'Z' (Req 2.1).
    if not is_valid_timestamp(obj.get("timestamp")):
        failing.append("timestamp")

    # Integer fields: required ints in [0, 1_000_000] (Req 2.2).
    for field in INTEGER_FIELDS:
        value = obj.get(field)
        if not (_is_integer(value) and _INTEGER_MIN <= value <= _INTEGER_MAX):
            failing.append(field)

    # Minute fields: required numbers in [0, 100_000] (Req 2.3).
    for field in MINUTE_FIELDS:
        value = obj.get(field)
        if not (_is_real_number(value) and _MINUTE_MIN <= value <= _MINUTE_MAX):
            failing.append(field)

    # confidence_score: required number in [0, 1] (Req 2.4).
    confidence = obj.get("confidence_score")
    if not (_is_real_number(confidence) and _CONFIDENCE_MIN <= confidence <= _CONFIDENCE_MAX):
        failing.append("confidence_score")

    # slowest_lane_id: optional — null or a well-formed identifier (Req 2.8).
    slowest_lane_id = obj.get("slowest_lane_id")
    if slowest_lane_id is not None and not is_valid_station_id(slowest_lane_id):
        failing.append("slowest_lane_id")

    if failing:
        return ValidationResult(is_valid=False, cleaned=None, failing_fields=failing)

    # Valid: build cleaned dict with exactly the Glossary fields (Req 2.7).
    cleaned = {field: obj[field] for field in GLOSSARY_FIELDS if field in obj}
    return ValidationResult(is_valid=True, cleaned=cleaned, failing_fields=[])
