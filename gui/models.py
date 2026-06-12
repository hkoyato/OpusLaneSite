"""Data model dataclasses for the Opus LaneSight GUI."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    source_mode: str = "file"  # "file" | "stream"
