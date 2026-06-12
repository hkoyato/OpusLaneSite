"""Property-based tests for the Station Identification feature.

Uses Hypothesis to verify the pure-logic correctness properties defined in the
station-identification design document. Each test validates a universal
invariant across generated inputs and is tagged with its design property.

The functions under test live in ``gui/station_validation.py`` and are pure
(no Qt dependency), so these tests need no QApplication and run headless via
``QT_QPA_PLATFORM=offscreen`` (set by tests/conftest.py).

Validates: Requirements 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.2
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from gui.station_validation import (
    DISPLAY_NAME_MAX_LEN,
    HEADER_DISPLAY_MAX_LEN,
    IDENTIFIER_MAX_LEN,
    IdentifierError,
    effective_display_name,
    header_label,
    validate_display_name,
    validate_station_identifier,
)

# Allowed identifier character set: lowercase letters, digits, hyphen, underscore.
_ALLOWED_IDENTIFIER_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def _is_valid_identifier(value: str) -> bool:
    """Reference predicate: valid iff 1-64 chars and only [a-z0-9_-]."""
    return (
        1 <= len(value) <= IDENTIFIER_MAX_LEN
        and all(c in _ALLOWED_IDENTIFIER_CHARS for c in value)
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid identifiers: 1-64 chars drawn from the allowed character set.
_valid_identifier_strategy = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)

# Whitespace-only strings (including empty) -> EMPTY error class.
_whitespace_only_strategy = st.text(alphabet=" \t\n\r\f\v", min_size=0, max_size=20)

# Over-length strings (> 64 chars). Drawn from the allowed set so length, not
# charset, is the disqualifier (the EMPTY/TOO_LONG/BAD_CHARSET ordering means a
# non-whitespace over-length string is classified TOO_LONG regardless of chars).
_over_length_strategy = st.text(
    alphabet=_ALLOWED_IDENTIFIER_CHARS, min_size=65, max_size=200
)


# ---------------------------------------------------------------------------
# Property 1: Station_Identifier validation
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 1: Station_Identifier validation


@given(s=st.text(max_size=200))
@settings(max_examples=100)
def test_identifier_validation_matches_specification(s: str) -> None:
    """**Validates: Requirements 2.1, 2.3, 2.4, 2.5**

    For any string s, validate_station_identifier(s) returns None iff s is
    1-64 chars and every char is in [a-z0-9_-]. Otherwise it returns the
    specific error: EMPTY when empty/whitespace-only, TOO_LONG when len > 64,
    BAD_CHARSET when 1-64 chars but containing a disallowed character.
    """
    result = validate_station_identifier(s)

    # Biconditional: no error iff the reference predicate accepts s.
    if _is_valid_identifier(s):
        assert result is None
    else:
        assert result is not None
        # Error classification follows the documented check ordering:
        #   empty/whitespace-only -> EMPTY
        #   length > 64           -> TOO_LONG
        #   otherwise             -> BAD_CHARSET
        if not s.strip():
            assert result is IdentifierError.EMPTY
        elif len(s) > IDENTIFIER_MAX_LEN:
            assert result is IdentifierError.TOO_LONG
        else:
            assert result is IdentifierError.BAD_CHARSET


@given(s=_valid_identifier_strategy)
@settings(max_examples=100)
def test_identifier_validation_accepts_valid(s: str) -> None:
    """**Validates: Requirements 2.1**

    Every 1-64 char string composed solely of [a-z0-9_-] is accepted.
    """
    assert validate_station_identifier(s) is None


@given(s=_whitespace_only_strategy)
@settings(max_examples=100)
def test_identifier_validation_empty_or_whitespace(s: str) -> None:
    """**Validates: Requirements 2.3**

    Empty or whitespace-only identifiers are rejected with EMPTY.
    """
    assert validate_station_identifier(s) is IdentifierError.EMPTY


@given(s=_over_length_strategy)
@settings(max_examples=100)
def test_identifier_validation_over_length(s: str) -> None:
    """**Validates: Requirements 2.5**

    Identifiers longer than 64 characters are rejected with TOO_LONG.
    """
    assert validate_station_identifier(s) is IdentifierError.TOO_LONG


# ---------------------------------------------------------------------------
# Property 2: Station_Display_Name validation
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 2: Station_Display_Name validation


@given(s=st.text(max_size=200))
@settings(max_examples=100)
def test_display_name_validation_matches_specification(s: str) -> None:
    """**Validates: Requirements 2.6, 2.7**

    For any string s, validate_display_name(s) returns True iff len(s) <= 128.
    """
    assert validate_display_name(s) == (len(s) <= DISPLAY_NAME_MAX_LEN)


# ---------------------------------------------------------------------------
# Property 3: Effective display name fallback
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 3: Effective display name fallback


@given(
    identifier=_valid_identifier_strategy,
    display_name=st.text(max_size=200),
)
@settings(max_examples=100)
def test_effective_display_name_fallback(identifier: str, display_name: str) -> None:
    """**Validates: Requirements 2.8**

    effective_display_name(i, d) equals d when d has at least one non-whitespace
    character, and equals i when d is empty or whitespace-only.
    """
    result = effective_display_name(identifier, display_name)

    if display_name.strip():
        assert result == display_name
    else:
        assert result == identifier


# ---------------------------------------------------------------------------
# Property 4: Header truncation
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 4: Header truncation


@given(s=st.text(min_size=0, max_size=120))
@settings(max_examples=100)
def test_header_truncation(s: str) -> None:
    """**Validates: Requirements 4.2**

    header_label(s) returns (s, None) when len(s) <= 40, and
    (s[:40] + "...", s) when len(s) > 40. The shown text never exceeds 43
    characters, and the full value is recoverable whenever truncation occurs.
    """
    shown, full = header_label(s)

    if len(s) <= HEADER_DISPLAY_MAX_LEN:
        assert shown == s
        assert full is None
    else:
        assert shown == s[:HEADER_DISPLAY_MAX_LEN] + "..."
        # Displayed text never exceeds 40 + len("...") == 43 characters.
        assert len(shown) <= HEADER_DISPLAY_MAX_LEN + 3
        # Full, untruncated value is preserved for tooltip/focus exposure.
        assert full == s


# ===========================================================================
# StationController properties (5-8): persistence-backed behaviour.
#
# These properties exercise StationController, a QObject, and the
# SettingsManager Config_Store. A QApplication is required for QObject
# construction and signal emission (no event loop is needed). Persistence is
# isolated per Hypothesis example by redirecting SettingsManager.CONFIG_DIR /
# CONFIG_FILE to a fresh temporary directory inside the test body (not a
# fixture), so Hypothesis re-running the body never touches the real user
# config and triggers no function-scoped fixture health check. deadline=None
# avoids flaky deadline failures caused by per-example disk I/O.
#
# Validates: Requirements 1.5, 1.6, 2.2, 3.1, 3.2, 3.5
# ===========================================================================

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gui.models import StationConfig
from gui.settings import SettingsManager
from gui.station_controller import StationController
from gui.station_validation import DEFAULT_STATION_IDENTIFIER

# A QApplication must exist before any QObject (StationController) is built.
# Reused across examples; signals fire synchronously without an event loop.
_app = QApplication.instance() or QApplication([])


@contextmanager
def _temp_config_store():
    """Redirect SettingsManager persistence to a throwaway temp directory.

    Restores the original class attributes and removes the temp tree on exit,
    so each Hypothesis example runs against an isolated, real-config-safe store.
    """
    tmp_root = tempfile.mkdtemp(prefix="station_pbt_")
    config_dir = Path(tmp_root) / "OpusLaneSight"
    config_file = config_dir / "settings.json"
    orig_dir = SettingsManager.CONFIG_DIR
    orig_file = SettingsManager.CONFIG_FILE
    SettingsManager.CONFIG_DIR = config_dir
    SettingsManager.CONFIG_FILE = config_file
    try:
        yield config_dir, config_file
    finally:
        SettingsManager.CONFIG_DIR = orig_dir
        SettingsManager.CONFIG_FILE = orig_file
        shutil.rmtree(tmp_root, ignore_errors=True)


def _settle(manager: SettingsManager) -> None:
    """Cancel the pending debounce Timer and flush synchronously.

    SettingsManager.update() schedules a 0.5s Timer save; cancelling it prevents
    a late write firing after the temp store is torn down, and an explicit
    save() guarantees the data is on disk before a fresh manager reads it.
    """
    if manager._save_timer is not None:
        manager._save_timer.cancel()
    manager.save()


# Valid display names: 0-128 chars (Property 2 accepts these).
_valid_display_name_strategy = st.text(max_size=DISPLAY_NAME_MAX_LEN)

# Valid StationConfig values: identifier passes Property 1, display passes
# Property 2.
_valid_config_strategy = st.builds(
    StationConfig,
    identifier=_valid_identifier_strategy,
    display_name=_valid_display_name_strategy,
)

# Invalid identifiers: any string that fails Property 1 validation.
_invalid_identifier_strategy = st.text(max_size=200).filter(
    lambda s: validate_station_identifier(s) is not None
)


# ---------------------------------------------------------------------------
# Property 5: Save sets the active configuration
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 5: Save sets the active configuration


@given(config=_valid_config_strategy)
@settings(max_examples=100, deadline=None)
def test_save_sets_active_configuration(config: StationConfig) -> None:
    """**Validates: Requirements 1.5, 2.2**

    For any valid StationConfig c, after controller.set_active(c) the call
    controller.active() returns a StationConfig equal to c.
    """
    with _temp_config_store():
        manager = SettingsManager()
        controller = StationController(manager)
        try:
            controller.set_active(config)
            assert controller.active() == config
        finally:
            _settle(manager)


# ---------------------------------------------------------------------------
# Property 6: Change detection
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 6: Change detection


@given(a=_valid_config_strategy, b=_valid_config_strategy)
@settings(max_examples=100, deadline=None)
def test_change_detection(a: StationConfig, b: StationConfig) -> None:
    """**Validates: Requirements 1.6**

    For any two StationConfig values a and b, setting the active config to a and
    then calling set_active(b) reports a change if and only if a != b (differing
    in identifier or display name).
    """
    with _temp_config_store():
        manager = SettingsManager()
        controller = StationController(manager)
        try:
            controller.set_active(a)
            changed = controller.set_active(b)
            assert changed == (a != b)
        finally:
            _settle(manager)


# ---------------------------------------------------------------------------
# Property 7: Persistence round-trip
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 7: Persistence round-trip


@given(config=_valid_config_strategy)
@settings(max_examples=100, deadline=None)
def test_persistence_round_trip(config: StationConfig) -> None:
    """**Validates: Requirements 3.1, 3.2**

    For any valid StationConfig c, saving c through a StationController (which
    writes station_id and station_display_name to the Config_Store) and then
    constructing a fresh SettingsManager/StationController over the same store
    yields an active StationConfig equal to c.
    """
    with _temp_config_store():
        writer_manager = SettingsManager()
        writer = StationController(writer_manager)
        writer.set_active(config)
        # Force a synchronous write rather than relying on the debounce Timer.
        _settle(writer_manager)

        reader_manager = SettingsManager()
        reader = StationController(reader_manager)
        try:
            assert reader.active() == config
        finally:
            _settle(reader_manager)


# ---------------------------------------------------------------------------
# Property 8: Invalid persisted identifier falls back to default
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 8: Invalid persisted identifier falls back to default


@given(invalid_identifier=_invalid_identifier_strategy)
@settings(max_examples=100, deadline=None)
def test_invalid_persisted_identifier_falls_back_to_default(
    invalid_identifier: str,
) -> None:
    """**Validates: Requirements 3.5**

    For any string persisted as station_id that fails Property 1 validation, a
    newly constructed StationController sets the active identifier to
    DEFAULT_STATION_IDENTIFIER.
    """
    with _temp_config_store() as (config_dir, config_file):
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"station_id": invalid_identifier}), encoding="utf-8"
        )

        manager = SettingsManager()
        controller = StationController(manager)
        try:
            assert controller.active_identifier() == DEFAULT_STATION_IDENTIFIER
        finally:
            _settle(manager)


# ===========================================================================
# Record producer properties (9-10): station_id capture and immutability.
#
# These properties exercise the Qt-free record producers in
# gui/station_records.py together with StationController.active_identifier()
# as the "active identifier at the moment of creation" source. The same
# QApplication + temp Config_Store isolation used by Properties 5-8 applies:
# StationController is a QObject and persists through SettingsManager, so each
# Hypothesis example runs against a throwaway store via _temp_config_store()
# and flushes the debounce Timer via _settle(). deadline=None avoids flaky
# deadline failures from per-example disk I/O.
#
# Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
# ===========================================================================

from gui.station_records import (
    build_station_metric_snapshot,
    build_vehicle_session,
    build_zone_event,
)

# The three record producers share the (fields, station_id) -> dict contract.
_record_producer_strategy = st.sampled_from(
    [build_vehicle_session, build_zone_event, build_station_metric_snapshot]
)


# ---------------------------------------------------------------------------
# Property 9: Produced records capture the active identifier
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 9: Produced records capture the active identifier


@given(producer=_record_producer_strategy, identifier=_valid_identifier_strategy)
@settings(max_examples=100, deadline=None)
def test_produced_records_capture_active_identifier(producer, identifier: str) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

    For any valid active identifier i and any of the three record producers
    (Vehicle_Session, Zone_Event, Station_Metric_Snapshot), the produced
    record's station_id is non-empty and equal to i as returned by
    active_identifier() at the moment the record is created.
    """
    with _temp_config_store():
        manager = SettingsManager()
        controller = StationController(manager)
        try:
            # Seed the controller so active_identifier() returns i, then build
            # the record from the identifier captured at creation time.
            controller.set_active(StationConfig(identifier, ""))
            captured = controller.active_identifier()
            record = producer({}, captured)

            assert record["station_id"] == identifier
            assert record["station_id"] != ""
            # The captured value is exactly what active_identifier() returns.
            assert record["station_id"] == controller.active_identifier()
        finally:
            _settle(manager)


# ---------------------------------------------------------------------------
# Property 10: Record identifier immutability
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 10: Record identifier immutability


@given(
    producer=_record_producer_strategy,
    a=_valid_identifier_strategy,
    b=_valid_identifier_strategy,
)
@settings(max_examples=100, deadline=None)
def test_record_identifier_immutability(producer, a: str, b: str) -> None:
    """**Validates: Requirements 5.5**

    For any two valid identifiers a and b, a record created while the active
    identifier is a, then changing the active identifier to b after creation,
    leaves the record's station_id equal to a. station_id is a plain str copied
    by value, so a later change to the active config cannot mutate the record.
    """
    with _temp_config_store():
        manager = SettingsManager()
        controller = StationController(manager)
        try:
            controller.set_active(StationConfig(a, ""))
            record = producer({}, controller.active_identifier())
            assert record["station_id"] == a

            # Change the active identifier after the record was created.
            controller.set_active(StationConfig(b, ""))

            # The previously-created record retains its original identifier.
            assert record["station_id"] == a
        finally:
            _settle(manager)


# ===========================================================================
# Report and wait-time properties (11-12): station identity in produced
# reports and wait-time payloads.
#
# These exercise the Qt-free builders in gui/station_report.py and
# gui/station_wait_time.py. They need no QApplication or Config_Store: the
# builders are pure functions over a StationConfig (or None). Property 11
# additionally round-trips an exported report through a throwaway temp file
# created inside the test body (not a function-scoped fixture, so Hypothesis
# re-running the body is safe) and cleaned up in a finally block.
#
# Validates: Requirements 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.3, 7.4
# ===========================================================================

from gui.station_report import (
    REPORT_STATION_DISPLAY_NAME_FIELD,
    REPORT_STATION_ID_FIELD,
    build_report,
    export_report,
)
from gui.station_wait_time import (
    WAIT_TIME_STATION_DISPLAY_NAME_FIELD,
    WAIT_TIME_STATION_ID_FIELD,
    build_wait_time_output,
)

# Small report/metrics content: JSON-serializable string-keyed dicts so the
# export round-trip parses back cleanly.
_content_strategy = st.dictionaries(st.text(max_size=10), st.integers(), max_size=5)


# ---------------------------------------------------------------------------
# Property 11: Reports include the station identity
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 11: Reports include the station identity


@given(
    content=_content_strategy,
    config=st.one_of(st.none(), _valid_config_strategy),
)
@settings(max_examples=100)
def test_reports_include_station_identity(content: dict, config) -> None:
    """**Validates: Requirements 6.1, 6.2, 6.3, 6.5**

    For any StationConfig c (or None) and report content, build_report includes
    a station identifier equal to c.identifier when c is not None and equal to
    DEFAULT_STATION_IDENTIFIER when c is None; when c is not None it also
    includes the effective display name. An exported report file, parsed back,
    contains the same station identifier under its station_id field.
    """
    report = build_report(content, config)

    if config is not None:
        expected_identifier = config.identifier
        assert report[REPORT_STATION_ID_FIELD] == config.identifier
        assert (
            report[REPORT_STATION_DISPLAY_NAME_FIELD]
            == config.effective_display_name
        )
    else:
        expected_identifier = DEFAULT_STATION_IDENTIFIER
        assert report[REPORT_STATION_ID_FIELD] == DEFAULT_STATION_IDENTIFIER

    # Export round-trip: the written file carries the same identifier under the
    # fixed station_id field (Req 6.3).
    tmp_root = tempfile.mkdtemp(prefix="station_report_pbt_")
    try:
        export_path = Path(tmp_root) / "report.json"
        export_report(report, export_path)
        parsed = json.loads(export_path.read_text(encoding="utf-8"))
        assert parsed["station_id"] == expected_identifier
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 12: Wait-time output includes the station identity under fixed
# field names
# ---------------------------------------------------------------------------
# Feature: station-identification, Property 12: Wait-time output includes the station identity under fixed field names


@given(metrics=_content_strategy, config=_valid_config_strategy)
@settings(max_examples=100)
def test_wait_time_output_includes_station_identity(
    metrics: dict, config: StationConfig
) -> None:
    """**Validates: Requirements 7.1, 7.2, 7.3, 7.4**

    For any valid StationConfig c, build_wait_time_output produces a payload
    whose value at WAIT_TIME_STATION_ID_FIELD ("station_id") equals
    c.identifier and whose value at WAIT_TIME_STATION_DISPLAY_NAME_FIELD
    ("station_display_name") equals c.effective_display_name. The field names
    are fixed wire constants that remain unchanged across releases.
    """
    # Fixed wire field names (Req 7.3, 7.4): the constants must be exactly these
    # literal strings so downstream API consumers can rely on them.
    assert WAIT_TIME_STATION_ID_FIELD == "station_id"
    assert WAIT_TIME_STATION_DISPLAY_NAME_FIELD == "station_display_name"

    payload = build_wait_time_output(metrics, config)

    assert payload[WAIT_TIME_STATION_ID_FIELD] == config.identifier
    assert (
        payload[WAIT_TIME_STATION_DISPLAY_NAME_FIELD]
        == config.effective_display_name
    )
