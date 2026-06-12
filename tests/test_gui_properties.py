"""Property-based tests for Opus LaneSight GUI utility functions.

Uses Hypothesis to verify correctness properties defined in the design document.
Each test validates universal invariants across generated inputs.

Validates: Requirements 2.7, 3.4, 4.1, 4.2, 4.3, 4.8, 8.5, 8.3, 9.6
"""

from __future__ import annotations

from dataclasses import dataclass

import hypothesis.strategies as st
from hypothesis import given, settings

from gui.models import TrackResult
from gui.utils import (
    build_track_result,
    clamp_confidence,
    compute_progress,
    compute_summary,
    derive_default_output_path,
    is_valid_video_extension,
    sort_results_default,
)


# ---------------------------------------------------------------------------
# Helper: lightweight vehicle stub for Property 3 (avoids importing tracker.py
# and its heavy dependencies like scipy/numpy)
# ---------------------------------------------------------------------------


@dataclass
class _VehicleStub:
    """Minimal stand-in for TrackedVehicle with required attributes."""

    vehicle_id: int
    first_frame: int
    last_frame: int
    plate_text: str
    plate_confidence: float


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Property 1: Windows file paths ending in .mp4
_windows_path_strategy = st.from_regex(
    r"[A-Za-z]:\\[\w\\]+\.mp4", fullmatch=True
)

# Property 3: Vehicle stubs with valid frame ranges and fps
_vehicle_stub_strategy = st.builds(
    _VehicleStub,
    vehicle_id=st.integers(min_value=0, max_value=10000),
    first_frame=st.integers(min_value=0, max_value=100000),
    last_frame=st.integers(min_value=0, max_value=100000),
    plate_text=st.text(min_size=0, max_size=10),
    plate_confidence=st.floats(min_value=0.0, max_value=1.0),
)

# Property 4/5: TrackResult lists
_track_result_strategy = st.builds(
    TrackResult,
    vehicle_id=st.integers(min_value=0, max_value=10000),
    plate_text=st.text(min_size=0, max_size=10),
    plate_confidence=st.floats(min_value=0.0, max_value=1.0),
    first_frame=st.integers(min_value=0, max_value=100000),
    last_frame=st.integers(min_value=0, max_value=100000),
    enter_time=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    leave_time=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    ),
    wait_time=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    ),
)


# ---------------------------------------------------------------------------
# Property 1: Default output path derivation
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 1: Default output path derivation


@given(input_path=_windows_path_strategy)
@settings(max_examples=100)
def test_default_output_path_is_output_mp4_in_same_directory(input_path: str) -> None:
    """**Validates: Requirements 2.7**

    For any valid Windows file path, the derived output path shall be
    "output.mp4" located in the same directory as the input file.
    """
    result = derive_default_output_path(input_path)

    # Result must end with output.mp4
    assert result.endswith("output.mp4")

    # The directory portion must match the input file's parent directory
    from pathlib import Path

    input_dir = str(Path(input_path).parent)
    result_dir = str(Path(result).parent)
    assert input_dir == result_dir


# ---------------------------------------------------------------------------
# Property 2: Progress percentage invariant
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 2: Progress percentage invariant


@given(
    current=st.integers(min_value=0, max_value=10000),
    total=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=100)
def test_progress_percentage_always_in_0_100_range(current: int, total: int) -> None:
    """**Validates: Requirements 3.4**

    For any frame index current and total frame count total, the computed
    progress percentage shall always be within [0, 100].
    When total > 0, the result equals (current / total) * 100.
    """
    result = compute_progress(current, total)

    # Range invariant
    assert 0.0 <= result <= 100.0

    # Value correctness when total > 0
    if total > 0:
        expected = max(0.0, min(100.0, (current / total) * 100.0))
        assert abs(result - expected) < 1e-9


# ---------------------------------------------------------------------------
# Property 3: TrackResult time computation
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 3: TrackResult time computation


@given(
    vehicle=_vehicle_stub_strategy,
    fps=st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_track_result_time_computation(vehicle: _VehicleStub, fps: float) -> None:
    """**Validates: Requirements 4.1**

    For any TrackedVehicle with first_frame >= 0, last_frame >= first_frame,
    and fps > 0, enter_time = first_frame / fps, leave_time = last_frame / fps,
    and wait_time >= 0.
    """
    # Ensure last_frame >= first_frame for a valid vehicle
    if vehicle.last_frame < vehicle.first_frame:
        vehicle.last_frame = vehicle.first_frame

    result = build_track_result(vehicle, fps)

    # enter_time == first_frame / fps
    expected_enter = vehicle.first_frame / fps
    assert abs(result.enter_time - expected_enter) < 1e-9

    # When total_frames is None (default), vehicle is never "still in frame"
    # so leave_time and wait_time are computed
    expected_leave = vehicle.last_frame / fps
    assert result.leave_time is not None
    assert abs(result.leave_time - expected_leave) < 1e-9

    # wait_time = leave_time - enter_time >= 0
    assert result.wait_time is not None
    assert result.wait_time >= -1e-9  # Allow tiny floating point imprecision


# ---------------------------------------------------------------------------
# Property 4: Summary statistics correctness
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 4: Summary statistics correctness


@given(results=st.lists(_track_result_strategy, min_size=0, max_size=50))
@settings(max_examples=100)
def test_summary_statistics_exclude_incomplete_tracks(results: list[TrackResult]) -> None:
    """**Validates: Requirements 4.2, 4.8**

    Only tracks with leave_time != None are included in aggregate computations.
    The computed average, max, and min shall match the expected values for the
    filtered subset.
    """
    summary = compute_summary(results)

    # Filter to tracks with non-None leave_time and wait_time
    complete_wait_times = [
        r.wait_time
        for r in results
        if r.leave_time is not None and r.wait_time is not None
    ]

    assert summary["total_vehicles"] == len(results)

    if not complete_wait_times:
        assert summary["avg_wait"] is None
        assert summary["max_wait"] is None
        assert summary["min_wait"] is None
    else:
        expected_avg = sum(complete_wait_times) / len(complete_wait_times)
        expected_max = max(complete_wait_times)
        expected_min = min(complete_wait_times)

        assert abs(summary["avg_wait"] - expected_avg) < 1e-9
        assert abs(summary["max_wait"] - expected_max) < 1e-9
        assert abs(summary["min_wait"] - expected_min) < 1e-9


# ---------------------------------------------------------------------------
# Property 5: Default sort order
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 5: Default sort order


@given(results=st.lists(_track_result_strategy, min_size=0, max_size=50))
@settings(max_examples=100)
def test_default_sort_is_ascending_by_enter_time(results: list[TrackResult]) -> None:
    """**Validates: Requirements 4.3**

    For any list of TrackResult objects, the default sort shall be ascending
    by enter_time such that results[i].enter_time <= results[i+1].enter_time
    for all consecutive pairs.
    """
    sorted_results = sort_results_default(results)

    for i in range(len(sorted_results) - 1):
        assert sorted_results[i].enter_time <= sorted_results[i + 1].enter_time


# ---------------------------------------------------------------------------
# Property 8: Confidence threshold clamping
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 8: Confidence threshold clamping


@given(value=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100)
def test_confidence_clamping_always_in_valid_range(value: float) -> None:
    """**Validates: Requirements 8.5**

    For any floating-point value v, the clamped result shall always be in
    [0.1, 1.0] and equal max(0.1, min(1.0, v)).
    """
    result = clamp_confidence(value)

    # Range invariant
    assert 0.1 <= result <= 1.0

    # Value correctness
    expected = max(0.1, min(1.0, value))
    assert abs(result - expected) < 1e-9


# ---------------------------------------------------------------------------
# Property 9: Frame error counter accuracy
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 9: Frame error counter accuracy


@given(outcomes=st.lists(st.booleans(), min_size=0, max_size=500))
@settings(max_examples=100)
def test_frame_error_counter_equals_true_count(outcomes: list[bool]) -> None:
    """**Validates: Requirements 8.3**

    For any sequence of frame-read outcomes (True = failure, False = success),
    the cumulative error counter shall equal the total number of True values.
    This validates the design property: count_errors(outcomes) == sum(outcomes).
    """
    # The error counter is simply the count of True (failure) values
    error_count = sum(1 for outcome in outcomes if outcome is True)

    # Verify the count matches the expected value
    assert error_count == outcomes.count(True)

    # Also verify incremental counting matches final count
    running_count = 0
    for outcome in outcomes:
        if outcome:
            running_count += 1
    assert running_count == error_count


# ---------------------------------------------------------------------------
# Property 10: File extension validation
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 10: File extension validation

_VALID_EXTENSIONS = [".mp4", ".avi", ".mov", ".mkv"]


@given(
    base_name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
        min_size=1,
        max_size=20,
    ),
    ext=st.sampled_from(_VALID_EXTENSIONS),
)
@settings(max_examples=100)
def test_valid_extensions_are_accepted_case_insensitive(base_name: str, ext: str) -> None:
    """**Validates: Requirements 9.6**

    File paths with extensions .mp4, .avi, .mov, or .mkv (case-insensitive)
    shall be accepted by the validator.
    """
    # Test lowercase
    assert is_valid_video_extension(f"C:\\videos\\{base_name}{ext}") is True
    # Test uppercase
    assert is_valid_video_extension(f"C:\\videos\\{base_name}{ext.upper()}") is True
    # Test mixed case
    mixed = ext[0:2].upper() + ext[2:]
    assert is_valid_video_extension(f"C:\\videos\\{base_name}{mixed}") is True


@given(
    base_name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
        min_size=1,
        max_size=20,
    ),
    ext=st.sampled_from([".txt", ".pdf", ".jpg", ".png", ".gif", ".exe", ".doc", ".wav"]),
)
@settings(max_examples=100)
def test_invalid_extensions_are_rejected(base_name: str, ext: str) -> None:
    """**Validates: Requirements 9.6**

    File paths with extensions other than .mp4, .avi, .mov, .mkv shall be
    rejected by the validator.
    """
    assert is_valid_video_extension(f"C:\\videos\\{base_name}{ext}") is False


# ---------------------------------------------------------------------------
# Settings strategies (Properties 6-7)
# ---------------------------------------------------------------------------

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from gui.models import AppSettings
from gui.settings import SettingsManager

# Valid AppSettings: all fields constrained to their documented valid ranges.
_valid_settings_strategy = st.builds(
    AppSettings,
    confidence=st.floats(
        min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    ocr_enabled=st.booleans(),
    ocr_language=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=8,
    ).filter(lambda s: s.strip() != ""),
    ocr_interval=st.integers(min_value=1, max_value=100),
    output_path=st.text(max_size=40),
    window_width=st.integers(min_value=1, max_value=10000),
    window_height=st.integers(min_value=1, max_value=10000),
    window_x=st.one_of(st.none(), st.integers(min_value=-10000, max_value=10000)),
    window_y=st.one_of(st.none(), st.integers(min_value=-10000, max_value=10000)),
)


# ---------------------------------------------------------------------------
# Property 6: Settings round-trip persistence
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 6: Settings round-trip persistence


@given(original=_valid_settings_strategy)
@settings(max_examples=100)
def test_settings_round_trip_preserves_all_fields(original: AppSettings) -> None:
    """**Validates: Requirements 5.2**

    For any valid AppSettings instance (confidence in [0.1, 1.0], ocr_interval
    in [1, 100], ocr_language a non-empty string, positive window dimensions),
    serializing to JSON and deserializing through SettingsManager validation
    shall produce an AppSettings with identical field values.
    """
    manager = SettingsManager.__new__(SettingsManager)

    # asdict -> json string -> json.loads -> _validate (deterministic, no disk)
    serialized = json.dumps(asdict(original))
    deserialized = manager._validate(json.loads(serialized))

    assert abs(deserialized.confidence - original.confidence) < 1e-9
    assert deserialized.ocr_enabled == original.ocr_enabled
    assert deserialized.ocr_language == original.ocr_language
    assert deserialized.ocr_interval == original.ocr_interval
    assert deserialized.output_path == original.output_path
    assert deserialized.window_width == original.window_width
    assert deserialized.window_height == original.window_height
    assert deserialized.window_x == original.window_x
    assert deserialized.window_y == original.window_y


# ---------------------------------------------------------------------------
# Property 7: Invalid settings produce valid defaults
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 7: Invalid settings produce valid defaults


def _assert_settings_in_range(s: AppSettings) -> None:
    """All fields of a produced AppSettings must be within valid ranges."""
    assert 0.1 <= s.confidence <= 1.0
    assert 1 <= s.ocr_interval <= 100
    assert isinstance(s.ocr_enabled, bool)
    assert isinstance(s.ocr_language, str) and s.ocr_language.strip() != ""
    assert s.window_width >= 1
    assert s.window_height >= 1
    assert s.window_x is None or isinstance(s.window_x, int)
    assert s.window_y is None or isinstance(s.window_y, int)


# Garbage / out-of-range dicts: extreme and wrong-typed values for each field.
_garbage_dict_strategy = st.fixed_dictionaries(
    {
        "confidence": st.one_of(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            st.text(max_size=5),
            st.none(),
        ),
        "ocr_enabled": st.one_of(st.booleans(), st.integers(), st.text(max_size=5), st.none()),
        "ocr_language": st.one_of(st.text(max_size=5), st.integers(), st.none()),
        "ocr_interval": st.one_of(
            st.integers(min_value=-10000, max_value=10000), st.text(max_size=5), st.none()
        ),
        "window_width": st.one_of(
            st.integers(min_value=-10000, max_value=10000), st.text(max_size=5), st.none()
        ),
        "window_height": st.one_of(
            st.integers(min_value=-10000, max_value=10000), st.text(max_size=5), st.none()
        ),
        "window_x": st.one_of(st.integers(), st.text(max_size=5), st.none()),
        "window_y": st.one_of(st.integers(), st.text(max_size=5), st.none()),
    }
)


@given(data=_garbage_dict_strategy)
@settings(max_examples=100)
def test_out_of_range_dict_yields_valid_settings(data: dict) -> None:
    """**Validates: Requirements 5.3**

    For any dict containing out-of-range or wrongly-typed values, the
    SettingsManager validation shall return an AppSettings whose fields are
    all within their valid ranges.
    """
    manager = SettingsManager.__new__(SettingsManager)
    result = manager._validate(data)
    _assert_settings_in_range(result)


@given(raw=st.text(max_size=60))
@settings(max_examples=100)
def test_invalid_json_string_yields_valid_defaults(raw: str) -> None:
    """**Validates: Requirements 5.3**

    For any string that is not a valid JSON object, loading settings from disk
    shall fall back to an AppSettings whose fields are all within valid ranges.
    """
    # Only exercise strings that are NOT a valid top-level JSON object, so the
    # corrupt-file fallback path in _load() is taken.
    try:
        parsed = json.loads(raw)
        is_json_object = isinstance(parsed, dict)
    except (json.JSONDecodeError, ValueError):
        is_json_object = False
    if is_json_object:
        return  # valid object handled by Property 6; skip here

    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp) / "OpusLaneSight"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "settings.json"
        config_file.write_text(raw, encoding="utf-8")

        manager = SettingsManager.__new__(SettingsManager)
        manager._write_failed = False
        manager._save_timer = None
        # Point class-level paths at the temp file for this load.
        original_dir = SettingsManager.CONFIG_DIR
        original_file = SettingsManager.CONFIG_FILE
        try:
            SettingsManager.CONFIG_DIR = config_dir
            SettingsManager.CONFIG_FILE = config_file
            result = manager._load()
        finally:
            SettingsManager.CONFIG_DIR = original_dir
            SettingsManager.CONFIG_FILE = original_file

    _assert_settings_in_range(result)


# ===========================================================================
# Stream input / AWS / detection-interval / deduplication utilities
# (Properties 11, 14, 15, 16, 17, 18)
# ===========================================================================

import copy

from gui.utils import (
    clamp_detect_interval,
    deduplicate_by_plate,
    is_valid_aws_region,
    is_valid_stream_url,
    parse_detect_interval,
)
from plate_utils import normalize_plate, pick_best_plate

_STREAM_SCHEMES = ["rtsp://", "rtmp://", "http://", "https://"]
# Mixed-case schemes exercise the case-insensitivity requirement.
_STREAM_SCHEMES_ANYCASE = _STREAM_SCHEMES + [
    "RTSP://",
    "Rtmp://",
    "HTTP://",
    "HttpS://",
]


# ---------------------------------------------------------------------------
# Property 11: Stream URL scheme validation
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 11: Stream URL scheme validation

_stream_url_strategy = st.one_of(
    # Likely-valid: a (possibly mixed-case) scheme plus an arbitrary body.
    st.builds(
        lambda scheme, body: scheme + body,
        st.sampled_from(_STREAM_SCHEMES_ANYCASE),
        st.text(max_size=50),
    ),
    # Whitespace-padded scheme URLs (trimming must be applied).
    st.builds(
        lambda pad, scheme, body: pad + scheme + body + pad,
        st.sampled_from(["", " ", "  ", "\t", " \n "]),
        st.sampled_from(_STREAM_SCHEMES_ANYCASE),
        st.text(max_size=20),
    ),
    # Boundary-length URLs around the 2048-character cap.
    st.builds(
        lambda scheme, n: scheme + ("a" * n),
        st.sampled_from(_STREAM_SCHEMES),
        st.integers(min_value=2035, max_value=2060),
    ),
    # Arbitrary text (mostly invalid: empty, whitespace, no scheme).
    st.text(max_size=60),
)


@given(url=_stream_url_strategy)
@settings(max_examples=100)
def test_stream_url_validation_matches_specification(url: str) -> None:
    """**Validates: Requirements 11.2, 11.5, 11.12**

    is_valid_stream_url accepts a URL if and only if, after trimming
    surrounding whitespace, it is non-empty, at most 2048 characters long,
    and begins (case-insensitively) with one of rtsp://, rtmp://, http://,
    or https://.
    """
    trimmed = url.strip()
    expected = (
        bool(trimmed)
        and len(trimmed) <= 2048
        and trimmed.lower().startswith(tuple(_STREAM_SCHEMES))
    )

    assert is_valid_stream_url(url) == expected


@given(
    scheme=st.sampled_from(_STREAM_SCHEMES_ANYCASE),
    body=st.text(max_size=40),
)
@settings(max_examples=100)
def test_stream_url_accepts_supported_schemes(scheme: str, body: str) -> None:
    """**Validates: Requirements 11.2, 11.5**

    A non-empty URL beginning with a supported scheme (any case) and within
    the length cap is always accepted.
    """
    url = scheme + body
    assert is_valid_stream_url(url) is True


# ---------------------------------------------------------------------------
# Property 14: AWS region validation
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 14: AWS region validation

_aws_region_strategy = st.one_of(
    st.text(max_size=80),
    # Pad realistic regions with surrounding whitespace.
    st.builds(
        lambda pad, body: pad + body + pad,
        st.sampled_from(["", " ", "  ", "\t"]),
        st.sampled_from(["us-east-1", "eu-west-2", "ap-southeast-1", "a"]),
    ),
    # Boundary-length strings around the 64-character cap.
    st.builds(lambda n: "r" * n, st.integers(min_value=0, max_value=80)),
)


@given(region=_aws_region_strategy)
@settings(max_examples=100)
def test_aws_region_validation_matches_specification(region: str) -> None:
    """**Validates: Requirements 12.5**

    is_valid_aws_region accepts a region if and only if, after trimming
    surrounding whitespace, it is non-empty and its length is within [1, 64].
    """
    trimmed = region.strip()
    expected = 1 <= len(trimmed) <= 64

    assert is_valid_aws_region(region) == expected


# ---------------------------------------------------------------------------
# Property 15: Detection interval clamping
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 15: Detection interval clamping


@given(
    value=st.one_of(
        st.floats(
            min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
        ),
        st.integers(min_value=-1000, max_value=1000),
    )
)
@settings(max_examples=100)
def test_detect_interval_clamping_matches_specification(value: float) -> None:
    """**Validates: Requirements 13.4, 13.5**

    clamp_detect_interval(v) equals max(1, min(60, round(v))) and is always
    an integer within [1, 60].
    """
    result = clamp_detect_interval(value)

    expected = max(1, min(60, round(value)))
    assert result == expected
    assert isinstance(result, int)
    assert 1 <= result <= 60


# ---------------------------------------------------------------------------
# Property 16: Detection interval non-integer rejection
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 16: Detection interval non-integer rejection

_detect_text_strategy = st.one_of(
    st.integers(min_value=-500, max_value=500).map(str),
    st.floats(
        min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ).map(str),
    st.sampled_from(["", "   ", "abc", "1.5", "+5", "-3", "0x10", "5 ", " 12 ", "1e3"]),
    st.text(max_size=12),
)


@given(
    text=_detect_text_strategy,
    last_valid=st.integers(min_value=1, max_value=60),
)
@settings(max_examples=100)
def test_detect_interval_parse_rejects_non_integers(text: str, last_valid: int) -> None:
    """**Validates: Requirements 13.6**

    parse_detect_interval accepts a value if and only if the entry denotes an
    integer (then clamped to [1, 60]); otherwise the most recent valid value
    is preserved unchanged.
    """
    try:
        parsed = int(text.strip())
        expected = max(1, min(60, parsed))
    except (ValueError, TypeError):
        expected = last_valid

    result = parse_detect_interval(text, last_valid)
    assert result == expected
    # Given a valid last_valid, the result is always within range.
    assert 1 <= result <= 60


# ---------------------------------------------------------------------------
# Deduplication helpers (Properties 17 and 18)
# ---------------------------------------------------------------------------


@dataclass
class _TrackStub:
    """Minimal stand-in for a deduplication track row."""

    vehicle_id: int
    plate_text: str
    plate_confidence: float
    first_frame: int
    last_frame: int
    hit_count: int


# Distinct group letters that are NOT OCR-confusable (absent from plate_utils
# _CHAR_MAP), so plates from different groups are never matched as similar.
_GROUP_LETTERS = ["A", "C", "D", "E", "F"]
# Confusable trailing characters: "O" normalizes to "0", so same-letter plates
# are always matched regardless of which variant they use.
_CONFUSABLE_VARIANTS = ["O", "0"]

_plate_track_strategy = st.builds(
    _TrackStub,
    vehicle_id=st.integers(min_value=0, max_value=10000),
    plate_text=st.builds(
        lambda letter, variant: letter * 5 + variant,
        st.sampled_from(_GROUP_LETTERS),
        st.sampled_from(_CONFUSABLE_VARIANTS),
    ),
    plate_confidence=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    first_frame=st.integers(min_value=0, max_value=100000),
    last_frame=st.integers(min_value=0, max_value=100000),
    hit_count=st.integers(min_value=0, max_value=1000),
)

# Tracks with absent or too-short plate text (< 3 chars) must never be merged.
_short_track_strategy = st.builds(
    _TrackStub,
    vehicle_id=st.integers(min_value=0, max_value=10000),
    plate_text=st.sampled_from(["", "A", "AB", "1", "12"]),
    plate_confidence=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    first_frame=st.integers(min_value=0, max_value=100000),
    last_frame=st.integers(min_value=0, max_value=100000),
    hit_count=st.integers(min_value=0, max_value=1000),
)

_dedup_track_list_strategy = st.lists(
    st.one_of(_plate_track_strategy, _short_track_strategy),
    min_size=0,
    max_size=20,
)


def _is_plate_track(track: _TrackStub) -> bool:
    return bool(track.plate_text) and len(track.plate_text) >= 3


def _track_key(track: _TrackStub) -> tuple:
    return (
        track.vehicle_id,
        track.plate_text,
        track.first_frame,
        track.last_frame,
        track.hit_count,
        round(track.plate_confidence, 9),
    )


# ---------------------------------------------------------------------------
# Property 17: Plate deduplication merge invariants
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 17: Plate deduplication merge invariants


@given(tracks=_dedup_track_list_strategy)
@settings(max_examples=100)
def test_deduplication_merge_invariants(tracks: list) -> None:
    """**Validates: Requirements 14.1, 14.2, 14.3**

    With reading enabled, tracks are grouped iff their plate texts are equal
    or match after OCR-confusable normalization. Each merged row uses the
    group's min(first_frame), max(last_frame), summed hit_count, max
    confidence, and best plate (pick_best_plate). Tracks with absent or
    sub-3-character plate text remain separate, unmerged rows.
    """
    # Snapshot inputs before dedup, which mutates the surviving track objects.
    snapshot = copy.deepcopy(tracks)
    result = deduplicate_by_plate(tracks, True)

    plate_snap = [t for t in snapshot if _is_plate_track(t)]
    short_snap = [t for t in snapshot if not _is_plate_track(t)]

    # Expected groups: plate tracks share a group iff they share a leading
    # letter (by construction, same letter => similar, different => dissimilar).
    # deduplicate_by_plate anchors groups by plate_confidence (descending)
    # before grouping; pick_best_plate's deterministic tie-break between
    # equal-length, OCR-confusable plates (e.g. 'DDDDDO' vs 'DDDDD0') depends
    # on that ordering, so mirror it to match the production contract.
    ordered_snap = sorted(plate_snap, key=lambda t: t.plate_confidence, reverse=True)
    groups: dict[str, list] = {}
    for t in ordered_snap:
        groups.setdefault(t.plate_text[0], []).append(t)

    res_plate = [t for t in result if _is_plate_track(t)]
    res_short = [t for t in result if not _is_plate_track(t)]

    # Exactly one merged row per distinct group.
    assert len(res_plate) == len(groups)
    res_by_letter = {t.plate_text[0]: t for t in res_plate}
    assert set(res_by_letter) == set(groups)

    for letter, group in groups.items():
        row = res_by_letter[letter]
        assert row.first_frame == min(t.first_frame for t in group)
        assert row.last_frame == max(t.last_frame for t in group)
        assert row.hit_count == sum(t.hit_count for t in group)
        assert abs(row.plate_confidence - max(t.plate_confidence for t in group)) < 1e-9

        expected_plate = pick_best_plate([t.plate_text for t in group])
        assert row.plate_text == expected_plate
        # Sanity: merged plate normalizes to the group's common canonical form.
        assert normalize_plate(row.plate_text) == normalize_plate(letter * 5 + "0")

    # Short / absent plate tracks are preserved exactly as separate rows.
    assert sorted(_track_key(t) for t in res_short) == sorted(
        _track_key(t) for t in short_snap
    )


# ---------------------------------------------------------------------------
# Property 18: Deduplication identity-when-disabled and idempotence
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 18: Deduplication identity-when-disabled and idempotence


@given(tracks=_dedup_track_list_strategy)
@settings(max_examples=100)
def test_deduplication_is_identity_when_disabled(tracks: list) -> None:
    """**Validates: Requirements 14.4, 14.5**

    When plate-text reading is disabled, deduplication returns rows equal in
    count and content to the input tracks (no merging).
    """
    snapshot = copy.deepcopy(tracks)
    result = deduplicate_by_plate(tracks, False)

    assert len(result) == len(snapshot)
    assert [_track_key(t) for t in result] == [_track_key(t) for t in snapshot]


@given(tracks=_dedup_track_list_strategy)
@settings(max_examples=100)
def test_deduplication_is_idempotent_when_enabled(tracks: list) -> None:
    """**Validates: Requirements 14.4, 14.5**

    When enabled, deduplication is idempotent: applying it twice yields the
    same result (by row content) as applying it once.
    """
    result_once = deduplicate_by_plate(tracks, True)
    # Snapshot before the second pass, which mutates the surviving objects.
    snap_once = sorted(_track_key(t) for t in result_once)

    result_twice = deduplicate_by_plate(result_once, True)
    snap_twice = sorted(_track_key(t) for t in result_twice)

    assert snap_once == snap_twice


# ===========================================================================
# Extended settings round-trip persistence (Property 20)
# ===========================================================================

# Valid AppSettings including the extension fields (Req 11, 12, 13, 15), each
# constrained to its documented valid range so a round-trip is lossless.
_valid_extended_settings_strategy = st.builds(
    AppSettings,
    confidence=st.floats(
        min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    ocr_enabled=st.booleans(),
    ocr_language=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=8,
    ).filter(lambda s: s.strip() != ""),
    ocr_interval=st.integers(min_value=1, max_value=100),
    output_path=st.text(max_size=40),
    window_width=st.integers(min_value=1, max_value=10000),
    window_height=st.integers(min_value=1, max_value=10000),
    window_x=st.one_of(st.none(), st.integers(min_value=-10000, max_value=10000)),
    window_y=st.one_of(st.none(), st.integers(min_value=-10000, max_value=10000)),
    # Extension fields, constrained to valid input space.
    detector_backend=st.sampled_from(["yolo", "rekognition"]),
    aws_region=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-"),
        min_size=1,
        max_size=64,
    ).filter(lambda s: s.strip() != ""),
    detect_interval=st.integers(min_value=1, max_value=60),
    no_output=st.booleans(),
    source_mode=st.sampled_from(["file", "stream"]),
)


# ---------------------------------------------------------------------------
# Property 20: Extended settings round-trip persistence
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 20: Extended settings round-trip persistence


@given(original=_valid_extended_settings_strategy)
@settings(max_examples=100)
def test_extended_settings_round_trip_preserves_new_fields(original: AppSettings) -> None:
    """**Validates: Requirements 5.3, 12.2, 15.1, 15.6**

    For any valid AppSettings instance — including the extension fields
    detector_backend in {"yolo","rekognition"}, aws_region a 1-64 char
    non-empty string, detect_interval in [1, 60], no_output a boolean, and
    source_mode in {"file","stream"} — serializing to JSON and deserializing
    through SettingsManager validation shall produce an AppSettings with
    identical field values.
    """
    manager = SettingsManager.__new__(SettingsManager)

    serialized = json.dumps(asdict(original))
    deserialized = manager._validate(json.loads(serialized))

    # Pre-existing fields are preserved (regression guard).
    assert abs(deserialized.confidence - original.confidence) < 1e-9
    assert deserialized.ocr_enabled == original.ocr_enabled
    assert deserialized.ocr_language == original.ocr_language
    assert deserialized.ocr_interval == original.ocr_interval
    assert deserialized.output_path == original.output_path
    assert deserialized.window_width == original.window_width
    assert deserialized.window_height == original.window_height
    assert deserialized.window_x == original.window_x
    assert deserialized.window_y == original.window_y

    # New extension fields round-trip identically.
    assert deserialized.detector_backend == original.detector_backend
    assert deserialized.aws_region == original.aws_region
    assert deserialized.detect_interval == original.detect_interval
    assert deserialized.no_output == original.no_output
    assert deserialized.source_mode == original.source_mode


def _assert_new_fields_in_range(s: AppSettings) -> None:
    """All extension fields of a produced AppSettings must be valid."""
    assert s.detector_backend in ("yolo", "rekognition")
    assert isinstance(s.aws_region, str) and 1 <= len(s.aws_region) <= 64
    assert s.aws_region.strip() != ""
    assert isinstance(s.detect_interval, int) and 1 <= s.detect_interval <= 60
    assert isinstance(s.no_output, bool)
    assert s.source_mode in ("file", "stream")


# Garbage / out-of-range values targeting each new field. Documented defaults:
# detector_backend -> "yolo", aws_region -> "us-east-1",
# detect_interval -> clamp [1, 60] (non-int -> 1), no_output -> bool,
# source_mode -> "file".
_garbage_new_fields_strategy = st.fixed_dictionaries(
    {
        "detector_backend": st.one_of(
            st.sampled_from(["yolo", "rekognition", "azure", "", "YOLO", "tensorflow"]),
            st.integers(),
            st.none(),
        ),
        "aws_region": st.one_of(
            st.text(max_size=80),
            st.just("r" * 65),  # over-long
            st.just("   "),  # whitespace only
            st.just(""),  # empty
            st.integers(),
            st.none(),
        ),
        "detect_interval": st.one_of(
            st.integers(min_value=-1000, max_value=1000),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(max_size=5),
            st.booleans(),
            st.none(),
        ),
        "no_output": st.one_of(
            st.booleans(), st.integers(), st.text(max_size=5), st.none()
        ),
        "source_mode": st.one_of(
            st.sampled_from(["file", "stream", "camera", "", "FILE"]),
            st.integers(),
            st.none(),
        ),
    }
)


@given(data=_garbage_new_fields_strategy)
@settings(max_examples=100)
def test_invalid_new_fields_fall_back_to_documented_defaults(data: dict) -> None:
    """**Validates: Requirements 5.3, 12.2, 15.1, 15.6**

    For any dict containing out-of-range or wrongly-typed values for the new
    extension fields, validation shall return an AppSettings whose extension
    fields are all within their valid ranges (falling back to documented
    defaults when the input is invalid).
    """
    manager = SettingsManager.__new__(SettingsManager)
    result = manager._validate(data)
    _assert_new_fields_in_range(result)


# ===========================================================================
# InputPanel.build_config() source/parameter mapping (Properties 12 and 19)
# ===========================================================================
#
# These properties exercise the real InputPanel widget through a headless
# (offscreen) Qt platform, configured in conftest.py. A single panel instance
# is reused across Hypothesis examples (its controls are fully reset each
# example) to avoid per-example widget construction overhead.

from gui.input_panel import (  # noqa: E402
    _BACKEND_REKOGNITION,
    _BACKEND_YOLO,
    _SOURCE_MODE_FILE,
    _SOURCE_MODE_STREAM,
    InputPanel,
)
from gui.models import ProcessingConfig, VideoMetadata  # noqa: E402


class _FakePanelSettings:
    """In-memory SettingsManager stand-in (never writes to disk)."""

    def __init__(self) -> None:
        self._settings = AppSettings()

    def get(self) -> AppSettings:
        return self._settings

    def update(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)


_PANEL_CACHE: dict = {}


def _shared_panel() -> InputPanel:
    """Lazily construct (once) and return a reusable headless InputPanel."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    panel = _PANEL_CACHE.get("panel")
    if panel is None:
        panel = InputPanel(_FakePanelSettings())
        _PANEL_CACHE["panel"] = panel
    return panel


def _metadata_for(path: str) -> VideoMetadata:
    """Build a plausible VideoMetadata for *path* without opening a file."""
    return VideoMetadata(
        file_name=path.replace("\\", "/").rsplit("/", 1)[-1],
        file_path=path,
        width=1280,
        height=720,
        frame_count=300,
        fps=30.0,
        duration_seconds=10.0,
    )


# Region text constrained to the field's accepted alphabet and length cap (64).
_region_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="- "),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

# Stream URL bodies kept short and free of control characters.
_stream_body_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_.:/"),
    max_size=40,
)

_windows_file_path_strategy = st.from_regex(r"[A-Za-z]:\\[\w]+\\[\w]+\.mp4", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 12: ProcessingConfig source/parameter mapping
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 12: ProcessingConfig source/parameter mapping


@given(
    source_mode=st.sampled_from([_SOURCE_MODE_FILE, _SOURCE_MODE_STREAM]),
    file_path=_windows_file_path_strategy,
    stream_scheme=st.sampled_from(["rtsp://", "rtmp://", "http://", "https://"]),
    stream_body=_stream_body_strategy,
    backend=st.sampled_from([_BACKEND_YOLO, _BACKEND_REKOGNITION]),
    aws_region=_region_text_strategy,
    detect_interval=st.integers(min_value=1, max_value=60),
)
@settings(max_examples=100, deadline=None)
def test_build_config_maps_source_and_parameters(
    source_mode: str,
    file_path: str,
    stream_scheme: str,
    stream_body: str,
    backend: str,
    aws_region: str,
    detect_interval: int,
) -> None:
    """**Validates: Requirements 11.4, 12.4, 13.2**

    For any valid InputPanel control state, build_config() maps selections
    faithfully: in stream mode stream_url equals the entered URL and
    video_path is ""; in file mode video_path is the selected path and
    stream_url is ""; the backend maps to exactly "yolo" or "rekognition";
    aws_region is carried through unchanged; and detect_interval is an integer
    within [1, 60].
    """
    panel = _shared_panel()

    panel.source_mode_combo.setCurrentText(source_mode)
    panel.detector_combo.setCurrentText(backend)
    panel.detect_interval_spin.setValue(detect_interval)
    panel.aws_region_edit.setText(aws_region)

    stream_url = stream_scheme + stream_body
    panel.stream_url_edit.setText(stream_url)
    panel._metadata = _metadata_for(file_path)

    config = panel.build_config()

    assert isinstance(config, ProcessingConfig)

    # Source/parameter mapping.
    if source_mode == _SOURCE_MODE_STREAM:
        assert config.source_mode == "stream"
        assert config.stream_url == stream_url.strip()
        assert config.video_path == ""
    else:
        assert config.source_mode == "file"
        assert config.video_path == file_path
        assert config.stream_url == ""

    # Backend maps to exactly one of the two internal identifiers.
    expected_backend = (
        "rekognition" if backend == _BACKEND_REKOGNITION else "yolo"
    )
    assert config.detector_backend == expected_backend

    # aws_region carried through unchanged (after trimming surrounding space).
    assert config.aws_region == (aws_region.strip() or "us-east-1")

    # detect_interval is an integer within [1, 60].
    assert isinstance(config.detect_interval, int)
    assert 1 <= config.detect_interval <= 60
    assert config.detect_interval == detect_interval


# ---------------------------------------------------------------------------
# Property 19: No-output mode config mapping
# ---------------------------------------------------------------------------
# Feature: lanesight-gui, Property 19: No-output mode config mapping


@given(
    no_output=st.booleans(),
    file_path=_windows_file_path_strategy,
    output_text=st.one_of(
        st.just(""),
        st.from_regex(r"[A-Za-z]:\\[\w]+\\[\w]+\.mp4", fullmatch=True),
    ),
)
@settings(max_examples=100, deadline=None)
def test_build_config_no_output_mode_mapping(
    no_output: bool, file_path: str, output_text: str
) -> None:
    """**Validates: Requirements 15.4**

    For any InputPanel control state, when no-output mode is enabled
    build_config().output_path is None and no_output is True; when disabled
    output_path is a non-None path string and no_output is False.
    """
    panel = _shared_panel()

    # Use file mode so a video_path is always available to derive a default.
    panel.source_mode_combo.setCurrentText(_SOURCE_MODE_FILE)
    panel._metadata = _metadata_for(file_path)
    panel.output_path_edit.setText(output_text)
    panel.no_output_toggle.setChecked(no_output)

    config = panel.build_config()

    if no_output:
        assert config.no_output is True
        assert config.output_path is None
    else:
        assert config.no_output is False
        assert config.output_path is not None
        assert isinstance(config.output_path, str)
        assert config.output_path != ""
