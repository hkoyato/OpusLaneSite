"""Data model dataclasses for the Opus LaneSight GUI."""

from __future__ import annotations

from dataclasses import dataclass, field

from gui.station_validation import (
    DEFAULT_STATION_IDENTIFIER,
    effective_display_name as _effective_display_name,
)


@dataclass
class ProcessingConfig:
    """Immutable configuration for a processing session."""

    video_path: str  # populated in file mode, "" in stream mode
    output_path: str | None  # None when No_Output_Mode is enabled (Req 15)
    confidence: float  # 0.1 – 1.0
    ocr_enabled: bool
    ocr_languages: list[str] = field(default_factory=lambda: ["en"])
    ocr_interval: int = 10  # 1 – 100
    plate_model_path: str | None = None
    # Input source (Req 11)
    source_mode: str = "file"  # "file" | "stream"
    stream_url: str = ""  # populated in stream mode, "" in file mode
    # Detector backend (Req 12) and interval (Req 13)
    detector_backend: str = "yolo"  # "yolo" | "rekognition"
    aws_region: str = "us-east-1"  # used when detector_backend == "rekognition"
    detect_interval: int = 1  # 1 – 60
    no_output: bool = False  # mirrors output_path is None (Req 15)
    auto_adjust: bool = False  # adaptive interval/resolution (Rekognition only)
    # Operator-configured number of active inspection lanes. The vision
    # pipeline cannot detect lanes from a single camera, so this is a manual
    # station override (product overview §14) that feeds the deterministic
    # wait-time formula instead of a fabricated constant.
    active_lanes: int = 1  # 1 – 99


@dataclass
class VideoMetadata:
    """Metadata extracted from a video file on selection."""

    file_name: str
    file_path: str
    width: int
    height: int
    frame_count: int
    fps: float
    duration_seconds: float  # frame_count / fps


@dataclass
class TrackResult:
    """Per-vehicle result computed from TrackedVehicle after processing."""

    vehicle_id: int
    plate_text: str  # empty if OCR disabled or no reading
    plate_confidence: float  # 0.0 if no reading
    first_frame: int
    last_frame: int
    enter_time: float  # first_frame / fps (seconds)
    leave_time: float | None  # last_frame / fps or None if still in frame
    wait_time: float | None  # leave_time - enter_time or None


@dataclass(frozen=True)
class StationConfig:
    """Immutable active station configuration (value object).

    frozen=True guarantees a config handed to a record producer cannot be
    mutated after the fact, reinforcing the capture-by-value record contract
    (Req 5.5).
    """

    identifier: str  # Station_Identifier, validated 1-64 [a-z0-9_-]
    display_name: str  # Station_Display_Name, 0-128 chars ("" allowed)

    @property
    def effective_display_name(self) -> str:
        """Display name when non-whitespace, else the identifier (Req 2.8)."""
        return _effective_display_name(self.identifier, self.display_name)

    @classmethod
    def default(cls) -> "StationConfig":
        """Default config: identifier and display name both the default
        identifier (Req 3.3)."""
        return cls(DEFAULT_STATION_IDENTIFIER, DEFAULT_STATION_IDENTIFIER)


@dataclass
class AppSettings:
    """Persisted application settings."""

    confidence: float = 0.5
    ocr_enabled: bool = False
    ocr_language: str = "en"
    ocr_interval: int = 10
    output_path: str = ""
    window_width: int = 1280
    window_height: int = 800
    window_x: int | None = None
    window_y: int | None = None
    # Extension persisted prefs (Req 12, 13, 15, 11)
    detector_backend: str = "yolo"  # "yolo" | "rekognition"
    aws_region: str = "us-east-1"  # 1 – 64 chars
    detect_interval: int = 1  # 1 – 60
    no_output: bool = False
    auto_adjust: bool = False  # adaptive interval/resolution (Rekognition only)
    source_mode: str = "file"  # "file" | "stream"
    # Operator-configured active inspection lanes (manual station override).
    active_lanes: int = 1  # 1 – 99
    # Station identity (station-identification spec, Req 3)
    station_id: str = "demo_station_01"  # Station_Identifier
    station_display_name: str = "demo_station_01"  # Station_Display_Name
    # Station Stats API publishing (station-stats-api spec)
    api_base_url: str = "https://m2tmgtt9n6.execute-api.us-west-2.amazonaws.com/prod"
    client_credential: str = "lanesight-demo-credential"
