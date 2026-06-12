"""Bounded, timestamp-ordered Pending_Snapshot_Buffer for the LaneSight_Client.

The ``PendingSnapshotBuffer`` holds snapshots that have not yet been
successfully published, per the design "Pending_Snapshot_Buffer" section and
Requirements 8.4 and 8.5:

- It is a bounded FIFO ordered by ascending snapshot timestamp, with a hard
  capacity of ``CAPACITY`` (1000).
- Ordering is by the *actual instant*: timestamps are compared as
  UTC-normalized ISO 8601 instants via
  :func:`station_stats_api.timestamps.to_utc_instant`, so two strings denoting
  the same moment under different offsets order equivalently
  (e.g. ``...-08:00`` and the equivalent ``Z`` form). This lets a recovery
  drain publish oldest-first in true chronological order (Requirement 8.5).
- When a snapshot is added while the buffer is already at capacity, the single
  earliest-timestamp snapshot (across the new and existing entries) is evicted
  and returned so the caller can surface a permanent-drop notification
  (Requirement 8.4).

Snapshots whose ``timestamp`` cannot be parsed as a valid offset/``Z`` ISO 8601
instant are ordered as if they were the earliest possible instant, so a
malformed timestamp never crashes buffering and such an entry is evicted first
under pressure rather than silently displacing well-formed snapshots.
"""

from __future__ import annotations

from bisect import insort
from datetime import datetime, timezone
from itertools import count
from typing import Iterator

from station_stats_api.timestamps import try_to_utc_instant

from .models import Snapshot

__all__ = ["PendingSnapshotBuffer"]

# An instant guaranteed to sort before any real UTC timestamp, used as the
# ordering key for snapshots whose timestamp cannot be parsed.
_MIN_INSTANT = datetime.min.replace(tzinfo=timezone.utc)


class PendingSnapshotBuffer:
    """A bounded FIFO of snapshots ordered by ascending UTC timestamp.

    The buffer never holds more than :attr:`CAPACITY` snapshots. Adding a
    snapshot at capacity evicts and returns the single earliest-timestamp
    snapshot. Ties on the normalized instant are broken by insertion order so
    behavior is deterministic and stable (FIFO among equal instants).
    """

    CAPACITY = 1000

    def __init__(self) -> None:
        # Each entry is a 3-tuple ``(instant, seq, snapshot)``. ``instant`` is
        # the UTC-normalized comparison key; ``seq`` is a strictly increasing
        # insertion counter that breaks ties deterministically (FIFO); the
        # list is kept sorted ascending so index 0 is always the oldest.
        self._entries: list[tuple[datetime, int, Snapshot]] = []
        self._seq = count()

    def _key(self, snapshot: Snapshot) -> datetime:
        """Return the UTC-normalized ordering instant for ``snapshot``.

        Falls back to a minimal instant for unparseable timestamps so ordering
        is total and never raises.
        """
        instant = try_to_utc_instant(snapshot.timestamp)
        return instant if instant is not None else _MIN_INSTANT

    def add(self, snapshot: Snapshot) -> Snapshot | None:
        """Insert ``snapshot`` maintaining ascending timestamp order.

        If the buffer is already at :attr:`CAPACITY`, the single oldest
        snapshot (by earliest UTC-normalized timestamp, across the newly added
        and existing entries) is evicted to make room.

        Args:
            snapshot: The snapshot to buffer for later publication.

        Returns:
            The evicted oldest snapshot when an addition occurs at capacity,
            otherwise ``None``.
        """
        entry = (self._key(snapshot), next(self._seq), snapshot)
        insort(self._entries, entry, key=lambda e: (e[0], e[1]))

        if len(self._entries) > self.CAPACITY:
            # Evict the single earliest entry (index 0 after sorted insert).
            _, _, evicted = self._entries.pop(0)
            return evicted
        return None

    def peek_oldest(self) -> Snapshot | None:
        """Return the oldest buffered snapshot without removing it.

        Returns:
            The earliest-timestamp snapshot, or ``None`` if the buffer is empty.
        """
        if not self._entries:
            return None
        return self._entries[0][2]

    def remove(self, snapshot: Snapshot) -> None:
        """Remove one occurrence of ``snapshot`` from the buffer.

        Matches by snapshot equality (``Snapshot`` is a frozen dataclass, so
        equality compares all fields). Removing a snapshot that is not present
        is a no-op.

        Args:
            snapshot: The snapshot to remove (e.g. after a successful publish
                or a terminal rejection).
        """
        for index, (_, _, candidate) in enumerate(self._entries):
            if candidate == snapshot:
                del self._entries[index]
                return

    def __len__(self) -> int:
        """Return the number of snapshots currently buffered."""
        return len(self._entries)

    def __iter__(self) -> Iterator[Snapshot]:
        """Iterate snapshots in ascending timestamp order (oldest first)."""
        return (snapshot for _, _, snapshot in self._entries)
