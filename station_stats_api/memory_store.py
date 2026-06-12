"""In-memory ``StatisticsStore`` fake for the Station_Stats_API.

:class:`InMemoryStatisticsStore` is a dependency-free implementation of the
:class:`station_stats_api.store.StatisticsStore` protocol. It holds exactly one
*current* snapshot per ``Station_Identifier`` in a plain dict and applies the
same last-write-wins-by-UTC-instant semantics the DynamoDB-backed adapter
(task 3.6) implements.

It exists so the snapshot/metrics handlers and the property tests can exercise
the storage logic without any AWS calls (see design.md "Statistics_Store" and
the Testing Strategy). The fake is the unit under property tests for the
latest-instant convergence, per-station independence, and idempotent
resubmission properties (Properties 6, 7, 10).

Storage behavior (Requirements 4.1–4.6, 8.8):

- A snapshot whose UTC-normalized timestamp is strictly later than the stored
  snapshot for the same ``station_id`` (or for which none exists) becomes the
  current snapshot -> :attr:`~station_stats_api.store.PutOutcome.STORED`.
- A resubmission with the same ``(station_id, timestamp)`` instant *and*
  identical snapshot content is an idempotent duplicate ->
  :attr:`~station_stats_api.store.PutOutcome.DUPLICATE`; the stored snapshot is
  left unchanged (Requirement 8.8).
- A snapshot whose instant is earlier than the stored snapshot, or equal to it
  but with different content, leaves the existing current snapshot unchanged ->
  :attr:`~station_stats_api.store.PutOutcome.RETAINED_EXISTING` (Requirement 4.3).

Each station is retained independently: storing a snapshot for one station
never alters another station's stored snapshot (Requirements 4.4, 4.5).
"""

from __future__ import annotations

import copy

from .store import PutOutcome
from .timestamps import to_utc_instant


class InMemoryStatisticsStore:
    """In-memory implementation of the :class:`StatisticsStore` protocol.

    Stores one current snapshot per ``station_id``. Snapshots are deep-copied
    on the way in and out so callers cannot mutate stored state through a shared
    reference, keeping each station's record isolated (Requirements 4.4, 4.5).
    """

    def __init__(self) -> None:
        # Maps station_id -> the stored current snapshot (a defensive copy).
        self._snapshots: dict[str, dict] = {}

    def put_if_newer(self, snapshot: dict) -> PutOutcome:
        """Store ``snapshot`` under last-write-wins semantics.

        See the module docstring and
        :meth:`station_stats_api.store.StatisticsStore.put_if_newer` for the
        full contract. Comparison is on the UTC-normalized instant of the
        ``timestamp`` field; the original timestamp string and every other
        field are preserved exactly as submitted.

        Args:
            snapshot: A validated, Glossary-field-only snapshot mapping that
                includes ``station_id`` and ``timestamp``.

        Returns:
            :attr:`PutOutcome.STORED` when the snapshot becomes the current
            snapshot, :attr:`PutOutcome.DUPLICATE` for an idempotent
            resubmission, or :attr:`PutOutcome.RETAINED_EXISTING` when the
            existing snapshot is kept unchanged.
        """
        station_id = snapshot["station_id"]
        new_instant = to_utc_instant(snapshot["timestamp"])

        existing = self._snapshots.get(station_id)
        if existing is None:
            # No current snapshot for this station: this one becomes current.
            self._snapshots[station_id] = copy.deepcopy(snapshot)
            return PutOutcome.STORED

        existing_instant = to_utc_instant(existing["timestamp"])

        if new_instant > existing_instant:
            # Strictly later instant wins (Requirement 4.2).
            self._snapshots[station_id] = copy.deepcopy(snapshot)
            return PutOutcome.STORED

        if new_instant == existing_instant and snapshot == existing:
            # Same instant and identical content: idempotent duplicate
            # resubmission; leave the stored snapshot unchanged (Req 8.8).
            return PutOutcome.DUPLICATE

        # Earlier instant, or equal instant with different content: retain the
        # existing current snapshot unchanged (Requirement 4.3).
        return PutOutcome.RETAINED_EXISTING

    def get(self, station_id: str) -> dict | None:
        """Return a copy of the current snapshot for ``station_id``.

        Args:
            station_id: The ``Station_Identifier`` to look up.

        Returns:
            A defensive copy of the stored current snapshot, or ``None`` if no
            snapshot is stored for that ``station_id`` (Requirement 5.2).
        """
        stored = self._snapshots.get(station_id)
        if stored is None:
            return None
        return copy.deepcopy(stored)

    def list_index(self) -> list[tuple[str, str]]:
        """Return ``(station_id, timestamp)`` for every stored station.

        The ``timestamp`` is the original submitted string of each station's
        current snapshot, preserved exactly as stored (Requirements 1.3, 5.3).

        Returns:
            A list of ``(station_id, timestamp)`` pairs, one per stored station;
            empty when no station has a stored snapshot (Requirement 5.6).
        """
        return [
            (station_id, stored["timestamp"])
            for station_id, stored in self._snapshots.items()
        ]
