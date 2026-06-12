"""Utility functions for the Opus LaneSight GUI."""

from __future__ import annotations

from pathlib import Path

from gui.models import TrackResult
from plate_utils import normalize_plate, pick_best_plate, plates_are_similar


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


# Stream URL schemes accepted in stream input mode (case-insensitive)
_VALID_STREAM_SCHEMES = ("rtsp://", "rtmp://", "http://", "https://")

_MAX_STREAM_URL_LENGTH = 2048
_MAX_AWS_REGION_LENGTH = 64

_MIN_DETECT_INTERVAL = 1
_MAX_DETECT_INTERVAL = 60


def is_valid_stream_url(url: str) -> bool:
    """Return True if *url* is an accepted stream URL.

    Leading/trailing whitespace is trimmed. A URL is accepted iff it is
    non-empty, at most 2048 characters long, and begins (case-insensitively)
    with one of ``rtsp://``, ``rtmp://``, ``http://`` or ``https://``.

    Validates: Requirements 11.2, 11.5
    """
    trimmed = url.strip()
    if not trimmed or len(trimmed) > _MAX_STREAM_URL_LENGTH:
        return False
    lowered = trimmed.lower()
    return lowered.startswith(_VALID_STREAM_SCHEMES)


def is_valid_aws_region(region: str) -> bool:
    """Return True if *region* is a plausible AWS region string.

    Leading/trailing whitespace is trimmed. A region is accepted iff it is
    non-empty and its trimmed length is in the inclusive range [1, 64].

    Validates: Requirements 12.5
    """
    trimmed = region.strip()
    return 1 <= len(trimmed) <= _MAX_AWS_REGION_LENGTH


def clamp_detect_interval(value: float) -> int:
    """Clamp *value* to the valid detection-interval range [1, 60].

    The value is rounded to the nearest integer and constrained to [1, 60].

    Validates: Requirements 13.4, 13.5
    """
    return max(_MIN_DETECT_INTERVAL, min(_MAX_DETECT_INTERVAL, round(value)))


def parse_detect_interval(text: str, last_valid: int) -> int:
    """Parse *text* into a clamped detection interval.

    When *text* denotes an integer, the parsed value is clamped to [1, 60]
    and returned. Otherwise (blank, non-numeric, or a non-integer such as a
    float) *last_valid* is returned unchanged.

    Validates: Requirements 13.4, 13.5, 13.6
    """
    try:
        parsed = int(text.strip())
    except (ValueError, TypeError):
        return last_valid
    return clamp_detect_interval(parsed)


def deduplicate_by_plate(tracks: list, enabled: bool) -> list:
    """Merge tracks that share the same or similar plate text.

    Replicates ``main._deduplicate_by_plate`` semantics using the fuzzy
    matching helpers from :mod:`plate_utils` (``plates_are_similar`` /
    ``normalize_plate`` / ``pick_best_plate``):

    - When *enabled* is False the input list is returned unchanged.
    - Tracks with no plate text, or plate text shorter than 3 characters,
      are never merged and remain as separate rows.
    - Remaining tracks are grouped by fuzzy plate similarity. Each merged
      row uses ``min(first_frame)``, ``max(last_frame)``, the summed
      ``hit_count``, the highest ``plate_confidence``, and the best plate
      text chosen by ``pick_best_plate``.

    The operation is idempotent: ``deduplicate_by_plate(deduplicate_by_plate(t,
    True), True)`` yields a list equivalent to a single application.

    Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5
    """
    if not enabled:
        return tracks

    plate_tracks = []
    no_plate_tracks = []
    for track in tracks:
        if track.plate_text and len(track.plate_text) >= 3:
            plate_tracks.append(track)
        else:
            no_plate_tracks.append(track)

    if not plate_tracks:
        return tracks

    # Highest-confidence tracks anchor each group first (mirrors main.py).
    plate_tracks.sort(key=lambda t: t.plate_confidence, reverse=True)

    groups: list[list] = []
    used: set[int] = set()
    for i, track in enumerate(plate_tracks):
        if i in used:
            continue
        group = [track]
        used.add(i)
        for j in range(i + 1, len(plate_tracks)):
            if j in used:
                continue
            if plates_are_similar(track.plate_text, plate_tracks[j].plate_text):
                group.append(plate_tracks[j])
                used.add(j)
        groups.append(group)

    merged_tracks = []
    for group in groups:
        if len(group) == 1:
            merged_tracks.append(group[0])
            continue

        best_plate = pick_best_plate([t.plate_text for t in group])

        # Highest hit_count track becomes the primary, as in main.py.
        group.sort(key=lambda t: getattr(t, "hit_count", 0), reverse=True)
        primary = group[0]
        primary.plate_text = best_plate
        primary.plate_confidence = max(t.plate_confidence for t in group)
        for other in group[1:]:
            primary.first_frame = min(primary.first_frame, other.first_frame)
            primary.last_frame = max(primary.last_frame, other.last_frame)
            if hasattr(primary, "hit_count"):
                primary.hit_count += getattr(other, "hit_count", 0)
        merged_tracks.append(primary)

    return merged_tracks + no_plate_tracks
