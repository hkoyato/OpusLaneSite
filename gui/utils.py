"""Utility functions for the Opus LaneSight GUI."""

from __future__ import annotations

from pathlib import Path

from gui.models import TrackResult


# Valid video extensions accepted by the application (case-insensitive)
_VALID_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv"})


def derive_default_output_path(input_path: str) -> str:
    """Return ``"output.mp4"`` in the same directory as *input_path*.

    Uses pathlib for cross-platform path operations.

    Validates: Requirements 2.7
    """
    return str(Path(input_path).parent / "output.mp4")


def compute_progress(current: int, total: int) -> float:
    """Compute processing progress as a percentage in [0, 100].

    Returns 0.0 when *total* is zero to avoid division by zero.

    Validates: Requirements 3.4
    """
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (current / total) * 100.0))


def clamp_confidence(value: float) -> float:
    """Clamp *value* to the valid confidence range [0.1, 1.0].

    Validates: Requirements 8.5
    """
    return max(0.1, min(1.0, value))


def is_valid_video_extension(path: str) -> bool:
    """Return True if *path* has an accepted video extension (case-insensitive).

    Accepted extensions: .mp4, .avi, .mov, .mkv

    Validates: Requirements 9.5, 9.6
    """
    ext = Path(path).suffix.lower()
    return ext in _VALID_VIDEO_EXTENSIONS


def build_track_result(
    vehicle,
    fps: float,
    total_frames: int | None = None,
) -> TrackResult:
    """Convert a TrackedVehicle instance into a :class:`TrackResult`.

    Parameters
    ----------
    vehicle:
        A ``TrackedVehicle`` from ``tracker.py``.
    fps:
        Video frames-per-second (must be > 0).
    total_frames:
        Total frame count of the video. If the vehicle's ``last_frame``
        is >= ``total_frames - 1``, the vehicle is considered still in-frame
        at the end of processing and ``leave_time`` / ``wait_time`` are set
        to ``None``.

    Validates: Requirements 4.1, 4.8
    """
    enter_time = vehicle.first_frame / fps

    still_in_frame = (
        total_frames is not None and vehicle.last_frame >= total_frames - 1
    )

    if still_in_frame:
        leave_time = None
        wait_time = None
    else:
        leave_time = vehicle.last_frame / fps
        wait_time = leave_time - enter_time

    return TrackResult(
        vehicle_id=vehicle.vehicle_id,
        plate_text=vehicle.plate_text or "",
        plate_confidence=vehicle.plate_confidence,
        first_frame=vehicle.first_frame,
        last_frame=vehicle.last_frame,
        enter_time=enter_time,
        leave_time=leave_time,
        wait_time=wait_time,
    )


def compute_summary(results: list[TrackResult]) -> dict:
    """Compute summary statistics from a list of track results.

    Only vehicles with a non-None ``leave_time`` (and therefore non-None
    ``wait_time``) are included in aggregate calculations.

    Returns a dict with keys:
        - ``total_vehicles``: total count of all results
        - ``avg_wait``: average wait time (float) or None if no complete tracks
        - ``max_wait``: maximum wait time (float) or None
        - ``min_wait``: minimum wait time (float) or None

    Validates: Requirements 4.2, 4.8
    """
    total_vehicles = len(results)
    wait_times = [
        r.wait_time for r in results if r.leave_time is not None and r.wait_time is not None
    ]

    if not wait_times:
        return {
            "total_vehicles": total_vehicles,
            "avg_wait": None,
            "max_wait": None,
            "min_wait": None,
        }

    return {
        "total_vehicles": total_vehicles,
        "avg_wait": sum(wait_times) / len(wait_times),
        "max_wait": max(wait_times),
        "min_wait": min(wait_times),
    }


def sort_results_default(results: list[TrackResult]) -> list[TrackResult]:
    """Return *results* sorted ascending by ``enter_time``.

    Validates: Requirements 4.3
    """
    return sorted(results, key=lambda r: r.enter_time)
