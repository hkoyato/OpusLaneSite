"""Report builder/exporter for the Opus LaneSight station identity.

Pure, Qt-free module. Embeds the active Station_Identifier and effective
Station_Display_Name into a report payload, and exports the report to a JSON
file that carries ``station_id`` as a field (station-identification spec,
Req 6).

Design contract:
  - ``build_report`` copies ``content`` (never mutates the input) and sets the
    station identity from the active StationConfig captured at production time.
  - When no active config is loaded (``config is None``), the report falls back
    to ``DEFAULT_STATION_IDENTIFIER`` for both the identifier and the display
    name (Req 6.5).
  - The identifier uses the fixed field name ``station_id`` so exported files
    consistently carry it (Req 6.3).
"""

from __future__ import annotations

import json
from pathlib import Path

from gui.models import StationConfig
from gui.station_validation import DEFAULT_STATION_IDENTIFIER

# Fixed report field names so exported files consistently carry the identity.
REPORT_STATION_ID_FIELD = "station_id"
REPORT_STATION_DISPLAY_NAME_FIELD = "station_display_name"

__all__ = [
    "REPORT_STATION_ID_FIELD",
    "REPORT_STATION_DISPLAY_NAME_FIELD",
    "build_report",
    "export_report",
]


def build_report(content: dict, config: StationConfig | None) -> dict:
    """Build a Report dict embedding the active station identity.

    Returns a new dict that merges ``content`` (copied, never mutated) with the
    station identity:
      - When ``config`` is not None: ``station_id`` -> ``config.identifier``
        (Req 6.1) and ``station_display_name`` -> ``config.effective_display_name``
        (Req 6.2).
      - When ``config`` is None (no active config): both fields fall back to
        ``DEFAULT_STATION_IDENTIFIER`` (Req 6.5).

    The identifier always uses the fixed field name ``station_id`` so exported
    files carry it consistently (Req 6.3).
    """
    report = dict(content)
    if config is not None:
        report[REPORT_STATION_ID_FIELD] = config.identifier
        report[REPORT_STATION_DISPLAY_NAME_FIELD] = config.effective_display_name
    else:
        report[REPORT_STATION_ID_FIELD] = DEFAULT_STATION_IDENTIFIER
        report[REPORT_STATION_DISPLAY_NAME_FIELD] = DEFAULT_STATION_IDENTIFIER
    return report


def export_report(report: dict, path: str | Path) -> None:
    """Write ``report`` to ``path`` as indented JSON (Req 6.3).

    The exported file carries the ``station_id`` field so, when parsed back, it
    contains the same station identifier under ``station_id``. The parent
    directory is created if it does not already exist.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
