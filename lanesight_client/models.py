"""Client-side data models for the LaneSight_Client.

These mirror the "Client-side models" section of the station-stats-api design
document. They cover the snapshot the detection pipeline produces, the client
configuration (whose credential must never be logged), and the enumeration of
submission outcomes the client maps HTTP responses to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

__all__ = ["Snapshot", "ClientConfig", "SubmitOutcome"]


@dataclass(frozen=True)
class Snapshot:
    """A single Station_Metric_Snapshot awaiting publication.

    Attributes:
        station_id: The active Station_Identifier the snapshot belongs to.
        timestamp: ISO 8601 date-time string as produced by the pipeline.
        payload: The full snapshot fields as a plain dict.
    """

    station_id: str
    timestamp: str
    payload: dict


@dataclass
class ClientConfig:
    """Configuration for the LaneSight_Client.

    The ``client_credential`` is sensitive and MUST never appear in logs or
    other output. ``__repr__`` is overridden so the credential is redacted
    even when a config instance is interpolated into a log line or traceback.
    """

    api_base_url: str | None
    client_credential: str | None

    def __repr__(self) -> str:
        # Never leak the credential. Only reveal whether one is configured.
        credential_state = "set" if self.client_credential else "None"
        return (
            f"ClientConfig(api_base_url={self.api_base_url!r}, "
            f"client_credential=<redacted:{credential_state}>)"
        )


class SubmitOutcome(Enum):
    """Outcome of a Submission_Attempt, derived from the HTTP response."""

    PUBLISHED = auto()  # 201
    DUPLICATE = auto()  # 200
    DISCARDED = auto()  # 400/422
    RETRY = auto()      # timeout/network/5xx/401/403
