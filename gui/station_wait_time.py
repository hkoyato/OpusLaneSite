"""Wait-time output builder for the Opus LaneSight station identity.

Pure, Qt-free module. Embeds the active Station_Identifier and effective
Station_Display_Name into the wait-time payload under fixed wire field names
that remain stable across releases (station-identification spec, Req 7).
"""

from __future__ import annotations

from gui.models import StationConfig

# Fixed wire field names. These MUST remain unchanged across application
# releases so downstream API consumers can route and label wait-time data by
# station (Req 7.3, 7.4).
WAIT_TIME_STATION_ID_FIELD = "station_id"
WAIT_TIME_STATION_DISPLAY_NAME_FIELD = "station_display_name"


def build_wait_time_output(metrics: dict, config: StationConfig) -> dict:
    """Build a Wait_Time_Output payload embedding the active station identity.

    Returns a new dict that merges ``metrics`` (copied, never mutated) with the
    active identifier and effective display name captured as of production time:
      - ``WAIT_TIME_STATION_ID_FIELD`` -> ``config.identifier`` (Req 7.1)
      - ``WAIT_TIME_STATION_DISPLAY_NAME_FIELD`` ->
        ``config.effective_display_name`` (Req 7.2)
    """
    payload = dict(metrics)
    payload[WAIT_TIME_STATION_ID_FIELD] = config.identifier
    payload[WAIT_TIME_STATION_DISPLAY_NAME_FIELD] = config.effective_display_name
    return payload
