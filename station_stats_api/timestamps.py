"""UTC timestamp normalization for the Station_Stats_API.

Snapshot timestamps are compared as UTC-normalized instants so that two
strings denoting the same moment compare equal regardless of how the offset
was written. For example::

    2026-06-12T13:45:00-08:00   and   2026-06-12T21:45:00Z

both denote the same instant and normalize to the same timezone-aware UTC
``datetime``.

This module only computes the comparable instant. The originally submitted
``timestamp`` string is preserved separately by the caller (the validator and
the Statistics_Store) and returned to consumers exactly as submitted
(Requirements 1.3, 5.3); only the normalized instant is used for ordering
(Requirement 4.2).

A value is accepted only when it is a valid ISO 8601 date-time that carries an
explicit UTC offset or the ``Z`` designator (Requirement 2.1). Naive values
(no offset) and otherwise unparseable values are rejected: :func:`to_utc_instant`
raises :class:`InvalidTimestampError`, while :func:`try_to_utc_instant` returns
the sentinel ``None``.
"""

from __future__ import annotations

from datetime import datetime, timezone


class InvalidTimestampError(ValueError):
    """Raised when a timestamp is not a valid ISO 8601 value with offset/``Z``.

    This covers strings that cannot be parsed as ISO 8601 date-times as well as
    naive date-times that omit an explicit UTC offset or the ``Z`` designator.
    """


def to_utc_instant(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp and return a comparable UTC instant.

    The returned ``datetime`` is timezone-aware and normalized to UTC, so two
    inputs denoting the same moment (e.g. an explicit offset and the equivalent
    ``Z`` form) compare equal.

    Args:
        timestamp: An ISO 8601 date-time string that includes an explicit UTC
            offset (e.g. ``-08:00``, ``+00:00``) or the ``Z`` designator.

    Returns:
        A timezone-aware :class:`datetime` in UTC suitable for ordering and
        equality comparison of instants.

    Raises:
        InvalidTimestampError: If ``timestamp`` is not a string, cannot be
            parsed as an ISO 8601 date-time, or is naive (lacks an explicit
            UTC offset or ``Z`` designator).
    """
    if not isinstance(timestamp, str):
        raise InvalidTimestampError(
            f"timestamp must be a string, got {type(timestamp).__name__}"
        )

    text = timestamp.strip()
    if not text:
        raise InvalidTimestampError("timestamp must be a non-empty string")

    # Accept the 'Z' designator explicitly. datetime.fromisoformat handles 'Z'
    # on modern Python, but normalizing here keeps behavior unambiguous and
    # independent of minor interpreter differences.
    normalized = text
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidTimestampError(
            f"timestamp is not a valid ISO 8601 date-time: {timestamp!r}"
        ) from exc

    # Reject naive timestamps: an explicit offset or 'Z' is required so the
    # instant is unambiguous (Requirement 2.1).
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidTimestampError(
            f"timestamp must include an explicit UTC offset or 'Z': {timestamp!r}"
        )

    return parsed.astimezone(timezone.utc)


def try_to_utc_instant(timestamp: object) -> datetime | None:
    """Return the UTC instant for ``timestamp`` or ``None`` if it is invalid.

    A non-raising companion to :func:`to_utc_instant` for call sites that
    prefer a sentinel over exception handling (e.g. boolean validation).

    Args:
        timestamp: A candidate timestamp value of any type.

    Returns:
        The timezone-aware UTC :class:`datetime`, or ``None`` if the value is
        not a valid ISO 8601 date-time with an explicit offset or ``Z``.
    """
    try:
        return to_utc_instant(timestamp)  # type: ignore[arg-type]
    except InvalidTimestampError:
        return None


def is_valid_timestamp(timestamp: object) -> bool:
    """Return whether ``timestamp`` is a valid offset/``Z`` ISO 8601 date-time.

    Args:
        timestamp: A candidate timestamp value of any type.

    Returns:
        ``True`` if the value parses as an ISO 8601 date-time with an explicit
        UTC offset or ``Z`` designator, ``False`` otherwise.
    """
    return try_to_utc_instant(timestamp) is not None
