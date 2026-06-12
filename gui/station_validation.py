"""Pure, Qt-free station identifier and display-name validation helpers.

These functions are the single source of validation truth shared by the
Station_Settings_View (live save) and the Config_Store (load-time
revalidation), per the Station Identification design.
"""

from __future__ import annotations

import re
from enum import Enum

DEFAULT_STATION_IDENTIFIER = "demo_station_01"

IDENTIFIER_MAX_LEN = 64
DISPLAY_NAME_MAX_LEN = 128
HEADER_DISPLAY_MAX_LEN = 40

# Allowed identifier characters: lowercase letters, digits, hyphen, underscore.
_IDENTIFIER_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


class IdentifierError(Enum):
    """Specific reason a Station_Identifier failed validation."""

    EMPTY = "empty"  # empty or whitespace-only (Req 2.3)
    TOO_LONG = "too_long"  # > 64 chars (Req 2.5)
    BAD_CHARSET = "bad_charset"  # 1-64 chars but illegal characters (Req 2.4)


def validate_station_identifier(value: str) -> IdentifierError | None:
    """Return None when ``value`` is a valid Station_Identifier, else the
    specific error.

    Valid iff 1-64 chars and only ``[a-z0-9_-]`` (Req 2.1).

    Order of checks fixes the error message shown:
      - empty/whitespace-only            -> EMPTY       (Req 2.3)
      - length > 64                      -> TOO_LONG    (Req 2.5)
      - illegal chars within 1-64 length -> BAD_CHARSET (Req 2.4)
      - valid                            -> None        (Req 2.1)
    """
    if not value.strip():
        return IdentifierError.EMPTY
    if len(value) > IDENTIFIER_MAX_LEN:
        return IdentifierError.TOO_LONG
    if _IDENTIFIER_RE.match(value) is None:
        return IdentifierError.BAD_CHARSET
    return None


def validate_display_name(value: str) -> bool:
    """Return True iff ``len(value) <= 128`` (Req 2.6). 0 length is valid (Req 2.7)."""
    return len(value) <= DISPLAY_NAME_MAX_LEN


def effective_display_name(identifier: str, display_name: str) -> str:
    """Return the user-facing label: the display name when it has non-whitespace
    content, otherwise the identifier (Req 2.8)."""
    if display_name.strip():
        return display_name
    return identifier


def header_label(display_name: str) -> tuple[str, str | None]:
    """Return ``(shown_text, full_text_or_None)`` for the header.

    When the label exceeds 40 chars, ``shown_text`` is the first 40 chars + '...'
    and ``full_text`` is the untruncated label for tooltip/focus exposure;
    otherwise ``full_text`` is None (Req 4.2).
    """
    if len(display_name) > HEADER_DISPLAY_MAX_LEN:
        return display_name[:HEADER_DISPLAY_MAX_LEN] + "...", display_name
    return display_name, None
