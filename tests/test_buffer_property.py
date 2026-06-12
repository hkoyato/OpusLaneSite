"""Property-based test for the LaneSight_Client Pending_Snapshot_Buffer.

Uses Hypothesis to verify the bounded-buffer correctness property defined in
the station-stats-api design document. The component under test,
``lanesight_client.buffer.PendingSnapshotBuffer``, is pure (no I/O, no Qt), so
the test runs headless and cheaply across many generated inputs.

The reference ordering used in the assertions is the same UTC-normalized
instant the buffer itself relies on, obtained via
``station_stats_api.timestamps.to_utc_instant``. Ties on the instant are broken
by insertion order, mirroring the buffer's deterministic FIFO-among-equals
behavior; each generated snapshot carries a unique insertion index in its
payload so the reference and the buffer agree on identity.

Validates: Requirements 8.4
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from lanesight_client.buffer import PendingSnapshotBuffer
from lanesight_client.models import Snapshot
from station_stats_api.timestamps import to_utc_instant

CAPACITY = PendingSnapshotBuffer.CAPACITY

# A spread of explicit UTC offsets plus the 'Z' designator so generated
# timestamps mix offset forms (Requirement 2.1 style inputs) and produce a
# wide range of UTC-normalized instants, including distinct strings that may
# denote the same instant.
_OFFSETS = ["Z", "+00:00", "-08:00", "+05:30", "-05:00", "+09:00", "+13:00"]


@st.composite
def iso_timestamps(draw: st.DrawFn) -> str:
    """Generate a valid ISO 8601 timestamp with an explicit offset or 'Z'."""
    base = datetime(2020, 1, 1, 0, 0, 0)
    # Second resolution with a bounded span keeps strings clean and makes
    # instant ties plausible, exercising tie-breaking by insertion order.
    offset_seconds = draw(st.integers(min_value=0, max_value=5_000_000))
    moment = base + timedelta(seconds=offset_seconds)
    suffix = draw(st.sampled_from(_OFFSETS))
    return moment.isoformat(timespec="seconds") + suffix


def _key(snapshot: Snapshot) -> tuple[datetime, int]:
    """Reference ordering key: (UTC-normalized instant, insertion index).

    This mirrors the buffer's internal ``(instant, seq)`` key, where ``seq`` is
    the strictly increasing insertion counter. Each snapshot's insertion index
    is stored in its payload so identity and ordering line up exactly.
    """
    return (to_utc_instant(snapshot.timestamp), snapshot.payload["i"])


# Feature: station-stats-api, Property 12: The pending buffer is bounded and evicts the oldest
@settings(
    max_examples=100,
    deadline=None,
    # The buffer must exceed its hard capacity of 1000 for eviction to occur,
    # so the smallest natural input is intentionally large.
    suppress_health_check=[HealthCheck.large_base_example, HealthCheck.too_slow],
)
@given(timestamps=st.lists(iso_timestamps(), min_size=CAPACITY + 1, max_size=CAPACITY + 50))
def test_buffer_is_bounded_and_evicts_the_oldest(timestamps: list[str]) -> None:
    """For any sequence of additions, the buffer length never exceeds CAPACITY,
    and whenever an addition occurs at capacity the evicted snapshot is exactly
    the single one with the earliest UTC-normalized timestamp (oldest first,
    ties broken by insertion order) among the buffer-plus-new set. After all
    additions the retained snapshots are the newest min(total, CAPACITY).
    """
    buffer = PendingSnapshotBuffer()
    # Each snapshot carries a unique insertion index so the reference key and
    # identity comparisons are unambiguous even when timestamps tie.
    snapshots = [
        Snapshot(station_id="demo_station_01", timestamp=ts, payload={"i": i})
        for i, ts in enumerate(timestamps)
    ]

    for snapshot in snapshots:
        at_capacity = len(buffer) == CAPACITY
        # Only the capacity steps need the (O(n)) candidate set, so the common
        # non-eviction path stays cheap.
        candidate = (list(buffer) + [snapshot]) if at_capacity else None

        evicted = buffer.add(snapshot)

        # Length invariant holds at every step.
        assert len(buffer) <= CAPACITY

        if at_capacity:
            assert candidate is not None
            # Exactly the single oldest snapshot is evicted (earliest instant,
            # ties broken by insertion order) and it is that very object.
            expected = min(candidate, key=_key)
            assert evicted is expected
            # Its instant is the earliest among the buffer-plus-new set.
            earliest_instant = min(to_utc_instant(c.timestamp) for c in candidate)
            assert to_utc_instant(evicted.timestamp) == earliest_instant
        else:
            # Below capacity, nothing is evicted.
            assert evicted is None

    # After all additions, the retained set is the newest min(total, CAPACITY)
    # by (instant, insertion order).
    total = len(snapshots)
    expected_retained = sorted(snapshots, key=_key)[max(0, total - CAPACITY):]
    expected_ids = sorted(s.payload["i"] for s in expected_retained)
    actual_ids = sorted(s.payload["i"] for s in buffer)
    assert len(buffer) == min(total, CAPACITY)
    assert actual_ids == expected_ids
