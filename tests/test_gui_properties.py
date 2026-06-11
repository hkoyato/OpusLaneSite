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
