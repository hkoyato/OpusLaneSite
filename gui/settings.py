"""Settings persistence for the Opus LaneSight GUI.

Loads and saves application settings as JSON at
%LOCALAPPDATA%\\OpusLaneSight\\settings.json.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from threading import Timer

from gui.models import AppSettings

logger = logging.getLogger(__name__)


class SettingsManager:
    """Manages application settings persistence.

    Handles missing files (creates with defaults), corrupt JSON (overwrites
    with defaults), out-of-range values (clamps to valid), and non-writable
    directories (operates in-memory with a warning flag).
    """

    CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "OpusLaneSight"
    CONFIG_FILE = CONFIG_DIR / "settings.json"

    def __init__(self) -> None:
        self._write_failed: bool = False
        self._save_timer: Timer | None = None
        self._settings: AppSettings = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self) -> AppSettings:
        """Return the current settings snapshot."""
        return self._settings

    def update(self, **kwargs: object) -> None:
        """Update one or more settings fields and persist immediately.

        Unknown keys are silently ignored.
        """
        valid_fields = {f.name for f in self._settings.__dataclass_fields__.values()}
        for key, value in kwargs.items():
            if key in valid_fields:
                setattr(self._settings, key, value)

        # Re-validate after mutation to clamp any out-of-range values
        self._settings = self._validate(asdict(self._settings))
        self._schedule_save()

    def save(self) -> None:
        """Write current settings to CONFIG_FILE as JSON.

        Creates the directory if it does not exist. If writing fails, sets
        the _write_failed flag and logs a warning.
        """
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._write_failed = True
            logger.warning("Cannot create settings directory %s: %s", self.CONFIG_DIR, exc)
            return

        try:
            data = asdict(self._settings)
            self.CONFIG_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            self._write_failed = False
        except OSError as exc:
            self._write_failed = True
            logger.warning("Cannot write settings file %s: %s", self.CONFIG_FILE, exc)

    @property
    def read_only(self) -> bool:
        """Return True if the settings file cannot be written (for UI warning)."""
        return self._write_failed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> AppSettings:
        """Load settings from CONFIG_FILE.

        Returns defaults if the file is missing or contains invalid JSON.
        Clamps out-of-range values via _validate.
        """
        try:
            raw = self.CONFIG_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Top-level JSON is not an object")
            return self._validate(data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Settings load fallback to defaults: %s", exc)
            return AppSettings()

    def _validate(self, data: dict) -> AppSettings:
        """Validate and clamp settings values, returning a valid AppSettings.

        - confidence: clamp to [0.1, 1.0]
        - ocr_interval: clamp to [1, 100]
        - ocr_enabled: coerce to bool
        - ocr_language: ensure non-empty string, default "en"
        - window dimensions: ensure positive integers
        - window_x / window_y: int or None
        - output_path: ensure string
        - detector_backend: one of {"yolo", "rekognition"}, default "yolo"
        - aws_region: non-empty string 1-64 chars, default "us-east-1"
        - detect_interval: clamp to [1, 60], non-int falls back to 1
        - no_output: coerce to bool
        - source_mode: one of {"file", "stream"}, default "file"
        - station_id: string; default "demo_station_01" when absent/non-string
        - station_display_name: string <= 128 chars (truncated); non-string
          falls back to station_id
        """
        # confidence
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.1, min(1.0, confidence))

        # ocr_enabled
        ocr_enabled = bool(data.get("ocr_enabled", False))

        # ocr_language
        ocr_language = data.get("ocr_language", "en")
        if not isinstance(ocr_language, str) or not ocr_language.strip():
            ocr_language = "en"

        # ocr_interval
        try:
            ocr_interval = int(data.get("ocr_interval", 10))
        except (TypeError, ValueError):
            ocr_interval = 10
        ocr_interval = max(1, min(100, ocr_interval))

        # output_path
        output_path = data.get("output_path", "")
        if not isinstance(output_path, str):
            output_path = ""

        # window_width
        try:
            window_width = int(data.get("window_width", 1280))
        except (TypeError, ValueError):
            window_width = 1280
        window_width = max(1, window_width)

        # window_height
        try:
            window_height = int(data.get("window_height", 800))
        except (TypeError, ValueError):
            window_height = 800
        window_height = max(1, window_height)

        # window_x
        raw_x = data.get("window_x", None)
        window_x: int | None = None
        if raw_x is not None:
            try:
                window_x = int(raw_x)
            except (TypeError, ValueError):
                window_x = None

        # window_y
        raw_y = data.get("window_y", None)
        window_y: int | None = None
        if raw_y is not None:
            try:
                window_y = int(raw_y)
            except (TypeError, ValueError):
                window_y = None

        # detector_backend
        detector_backend = data.get("detector_backend", "yolo")
        if detector_backend not in ("yolo", "rekognition"):
            detector_backend = "yolo"

        # aws_region
        aws_region = data.get("aws_region", "us-east-1")
        if (
            not isinstance(aws_region, str)
            or not (1 <= len(aws_region) <= 64)
            or not aws_region.strip()
        ):
            aws_region = "us-east-1"

        # detect_interval
        raw_interval = data.get("detect_interval", 1)
        if isinstance(raw_interval, bool) or not isinstance(raw_interval, int):
            detect_interval = 1
        else:
            detect_interval = max(1, min(60, raw_interval))

        # no_output
        no_output = bool(data.get("no_output", False))

        # auto_adjust
        auto_adjust = bool(data.get("auto_adjust", False))

        # active_lanes: operator-configured manual override. Clamp to [1, 99];
        # non-int (incl. bool) falls back to 1. Floored at 1 so the wait-time
        # formula never divides by zero.
        raw_lanes = data.get("active_lanes", 1)
        if isinstance(raw_lanes, bool) or not isinstance(raw_lanes, int):
            active_lanes = 1
        else:
            active_lanes = max(1, min(99, raw_lanes))

        # source_mode
        source_mode = data.get("source_mode", "file")
        if source_mode not in ("file", "stream"):
            source_mode = "file"

        # station_id: type/shape only; domain validation (Req 2) lives in
        # StationController. Default to "demo_station_01" when absent/non-string;
        # preserve the raw stored value as-is otherwise.
        station_id = data.get("station_id", "demo_station_01")
        if not isinstance(station_id, str):
            station_id = "demo_station_01"

        # station_display_name: string of length <= 128 (truncate longer values);
        # non-strings fall back to the validated station_id.
        station_display_name = data.get("station_display_name", station_id)
        if not isinstance(station_display_name, str):
            station_display_name = station_id
        elif len(station_display_name) > 128:
            station_display_name = station_display_name[:128]

        # api_base_url: string, default empty (unconfigured).
        api_base_url = data.get("api_base_url", "")
        if not isinstance(api_base_url, str):
            api_base_url = ""

        # client_credential: string, default empty (unconfigured).
        client_credential = data.get("client_credential", "")
        if not isinstance(client_credential, str):
            client_credential = ""

        return AppSettings(
            confidence=confidence,
            ocr_enabled=ocr_enabled,
            ocr_language=ocr_language,
            ocr_interval=ocr_interval,
            output_path=output_path,
            window_width=window_width,
            window_height=window_height,
            window_x=window_x,
            window_y=window_y,
            detector_backend=detector_backend,
            aws_region=aws_region,
            detect_interval=detect_interval,
            no_output=no_output,
            auto_adjust=auto_adjust,
            source_mode=source_mode,
            active_lanes=active_lanes,
            station_id=station_id,
            station_display_name=station_display_name,
            api_base_url=api_base_url,
            client_credential=client_credential,
        )

    def _schedule_save(self) -> None:
        """Save immediately (within the 2-second requirement).

        Uses a short debounce timer so rapid successive updates coalesce
        into a single disk write, but never exceed 2 seconds delay.
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
        # Debounce at 0.5s — well within the 2-second requirement
        self._save_timer = Timer(0.5, self.save)
        self._save_timer.daemon = True
        self._save_timer.start()
