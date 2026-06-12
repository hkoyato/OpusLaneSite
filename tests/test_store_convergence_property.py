"""Property-based test for latest-instant convergence in the Statistics_Store.

Uses Hypothesis to verify the convergence property defined in the
station-stats-api design document. The component under test,
``station_stats_api.memory_store.InMemoryStatisticsStore``, applies
last-write-wins-by-UTC-instant semantics with no I/O, so the test runs cheaply
across many generated inputs.

The reference ordering is the same UTC-normalized instant the store relies on,
obtained via ``station_stats_api.timestamps.to_utc_instant``. Generated
snapshots for a single station mix explicit offsets and the ``Z`` designator
(including distinct strings that denote the *same* instant) and vary their
non-key fields so snapshots differ in content.

Tie handling: when several snapshots share the latest instant the store keeps
the first one stored at that instant (later equal-instant snapshots are
RETAINED_EXISTING because their content differs), so the current snapshot is
the first snapshot in storage order whose UTC-normalized instant equals the
maximum. The assertions below pin down exactly that snapshot and also confirm
its instant equals the maximum.

Validates: Requirements 4.2, 4.3, 4.6
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.store import PutOutcome
from station_stats_api.timestamps import to_utc_instant

# Explicit UTC offsets plus the 'Z' designator. The same instant rendered with
# different entries here yields distinct strings that normalize to one instant,
# exercising offset/'Z' equivalence in the convergence logic (Requirement 4.6).
_OFFSETS: dict[str, timedelta] = {
    "Z": timedelta(0),
    "+00:00": timedelta(0),
    "-08:00": timedelta(hours=-8),
    "+05:30": timedelta(hours=5, minutes=30),
    "-05:00": timedelta(hours=-5),
    "+09:00": timedelta(hours=9),
    "+13:00": timedelta(hours=13),
}
_OFFSET_KEYS = list(_OFFSETS)

# A fixed UTC anchor; instants are this plus a drawn number of seconds.
_ANCHOR = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _render(instant_seconds: int, offset_key: str) -> str:
    """Render a fixed UTC instant as an ISO 8601 string in the given offset.

    The same ``instant_seconds`` rendered with different ``offset_key`` values
    produces different strings that all normalize to the same UTC instant.
    """
    utc_moment = _ANCHOR + timedelta(seconds=instant_seconds)
    if offset_key in ("Z", "+00:00"):
        text = utc_moment.replace(tzinfo=None).isoformat(timespec="seconds")
        return text + ("Z" if offset_key == "Z" else "+00:00")
    tz = timezone(_OFFSETS[offset_key])
    local = utc_moment.astimezone(tz)
    return local.isoformat(timespec="seconds")


def _snapshot(station_id: str, timestamp: str, marker: int) -> dict:
    """Build a Glossary-field-only snapshot whose content varies by ``marker``."""
    return {
        "station_id": station_id,
        "timestamp": timestamp,
        # vehicles_in_queue carries the unique marker so distinct snapshots
        # differ in content (kept within the valid [0, 1_000_000] range).
        "vehicles_in_queue": marker,
        "vehicles_in_bay": 3,
        "active_lanes": 3,
        "average_queue_wait_minutes": 14.2,
        "average_inspection_minutes": 6.4,
        "estimated_public_wait_minutes": 18,
        "throughput_per_hour": 28,
        "slowest_lane_id": "lane_2",
        "confidence_score": 0.82,
    }


_STATION_IDS = st.from_regex(r"\A[a-z0-9_-]{1,64}\Z")


@st.composite
def single_station_snapshots(draw: st.DrawFn) -> tuple[str, list[dict]]:
    """Generate a non-empty list of varied snapshots sharing one station_id.

    Timestamps mix offsets and 'Z' and include both distinct instants and the
    same instant expressed differently. Each snapshot has unique content via a
    per-index marker so none collide as idempotent duplicates.
    """
    station_id = draw(_STATION_IDS)
    # Draw one (instant_seconds, offset_key) pair per snapshot. Reusing an
    # instant with a different offset yields same-instant/different-string
    # snapshots; drawing distinct instants yields a clear unique maximum.
    pairs = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=5_000_000),
                st.sampled_from(_OFFSET_KEYS),
            ),
            min_size=1,
            max_size=25,
        )
    )
    snapshots = [
        _snapshot(station_id, _render(secs, off), marker)
        for marker, (secs, off) in enumerate(pairs)
    ]
    # Store them in a random order so convergence cannot depend on order.
    order = draw(st.permutations(list(range(len(snapshots)))))
    shuffled = [snapshots[i] for i in order]
    return station_id, shuffled


# Feature: station-stats-api, Property 6: The current snapshot is the latest instant, regardless of order
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(case=single_station_snapshots())
def test_current_snapshot_is_latest_instant_regardless_of_order(
    case: tuple[str, list[dict]],
) -> None:
    """After storing snapshots for one station in any order, the current
    snapshot is the one with the latest UTC-normalized instant; ties resolve to
    the first stored at that instant. Storing an earlier-or-equal instant never
    changes the current snapshot (Requirements 4.2, 4.3, 4.6).
    """
    station_id, snapshots = case
    store = InMemoryStatisticsStore()

    for snapshot in snapshots:
        store.put_if_newer(snapshot)

    max_instant = max(to_utc_instant(s["timestamp"]) for s in snapshots)
    # The store keeps the first snapshot (in storage order) that reaches the
    # maximum instant; later equal-instant snapshots are RETAINED_EXISTING.
    expected_current = next(
        s for s in snapshots if to_utc_instant(s["timestamp"]) == max_instant
    )

    current = store.get(station_id)
    assert current is not None
    # The current snapshot's instant is the latest among all stored snapshots.
    assert to_utc_instant(current["timestamp"]) == max_instant
    # And it is exactly the first snapshot that achieved that latest instant.
    assert current == expected_current

    # Req 4.3: storing a snapshot with an earlier instant must not change the
    # current snapshot.
    min_instant = min(to_utc_instant(s["timestamp"]) for s in snapshots)
    older_seconds = int((min_instant - _ANCHOR).total_seconds()) - 1
    older = _snapshot(station_id, _render(older_seconds, "Z"), marker=999_001)
    older_outcome = store.put_if_newer(older)
    assert older_outcome is PutOutcome.RETAINED_EXISTING
    assert store.get(station_id) == expected_current

    # Req 4.3: storing a snapshot at the SAME latest instant but with different
    # content also must not change the current snapshot.
    equal_instant_secs = int((max_instant - _ANCHOR).total_seconds())
    same_instant_other = _snapshot(
        station_id, _render(equal_instant_secs, "+05:30"), marker=999_002
    )
    same_outcome = store.put_if_newer(same_instant_other)
    assert same_outcome is PutOutcome.RETAINED_EXISTING
    assert store.get(station_id) == expected_current
