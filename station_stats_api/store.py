"""Statistics_Store adapter contract for the Station_Stats_API.

The Statistics_Store is the persistence seam that holds exactly one *current*
snapshot per ``Station_Identifier`` and applies last-write-wins semantics by
UTC-normalized timestamp. This module defines only the abstract contract:

- :class:`PutOutcome` — the named result of a write attempt.
- :class:`StatisticsStore` — the :class:`typing.Protocol` that both the
  in-memory fake (task 3.2) and the DynamoDB-backed adapter (task 3.6)
  implement.

Defining the contract on its own lets the snapshot/metrics handlers depend on
the protocol while property tests target an in-memory fake, so the storage
logic is verified without any AWS calls (see design.md "Statistics_Store").

The concrete implementations live in separate modules; this file intentionally
contains no storage behavior.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol, runtime_checkable

from .http_result import PUT_OUTCOME_STATUS


class PutOutcome(Enum):
    """The result of a :meth:`StatisticsStore.put_if_newer` attempt.

    Each outcome maps to the HTTP status the Snapshot handler returns. The
    mapping is mirrored by ``PUT_OUTCOME_STATUS`` in
    :mod:`station_stats_api.http_result`, keyed by the member *name*:

    - :attr:`STORED` -> ``201``: the snapshot's UTC-normalized timestamp was
      strictly later than the stored snapshot (or none existed), so it became
      the current snapshot (Requirements 4.1, 4.2).
    - :attr:`DUPLICATE` -> ``200``: a snapshot with the same
      ``(station_id, timestamp)`` was already stored, so the resubmission is
      idempotent and no conflicting record is created (Requirement 8.8).
    - :attr:`RETAINED_EXISTING` -> ``201``: the snapshot was valid and accepted
      but its instant was earlier than (or equal-but-different from) the stored
      snapshot, so the existing current snapshot is retained and unchanged
      (Requirement 4.3); the client still treats the request as published.
    """

    STORED = auto()
    DUPLICATE = auto()
    RETAINED_EXISTING = auto()

    @property
    def http_status(self) -> int:
        """The HTTP status code this outcome maps to (see ``PUT_OUTCOME_STATUS``)."""
        return PUT_OUTCOME_STATUS[self.name]


@runtime_checkable
class StatisticsStore(Protocol):
    """Persistence contract for the current snapshot per ``Station_Identifier``.

    Implementations store exactly one current snapshot per ``station_id`` and
    apply last-write-wins by UTC-normalized timestamp. The in-memory fake
    (task 3.2) and the DynamoDB-backed adapter (task 3.6) both satisfy this
    protocol, so handlers and property tests can depend on the abstraction
    rather than a concrete backend.
    """

    def put_if_newer(self, snapshot: dict) -> PutOutcome:
        """Store ``snapshot`` under last-write-wins semantics.

        Stores the snapshot iff its UTC-normalized timestamp is strictly later
        than the currently stored snapshot for the same ``station_id``, OR no
        snapshot exists for that ``station_id``.

        - Same ``(station_id, timestamp)`` as the stored snapshot ->
          :attr:`PutOutcome.DUPLICATE` (idempotent resubmission, Req 8.8).
        - Earlier-or-equal instant but a different snapshot ->
          :attr:`PutOutcome.RETAINED_EXISTING` (existing snapshot retained
          unchanged, Req 4.3).
        - Strictly later instant, or no existing snapshot ->
          :attr:`PutOutcome.STORED` (becomes the current snapshot, Req 4.2).

        Args:
            snapshot: A validated, Glossary-field-only snapshot mapping that
                includes ``station_id`` and ``timestamp``.

        Returns:
            The :class:`PutOutcome` describing how the write was resolved.
        """
        ...

    def get(self, station_id: str) -> dict | None:
        """Return the current snapshot for ``station_id``.

        Args:
            station_id: The ``Station_Identifier`` to look up.

        Returns:
            The stored current snapshot mapping, or ``None`` if no snapshot is
            stored for that ``station_id`` (Requirement 5.2).
        """
        ...

    def list_index(self) -> list[tuple[str, str]]:
        """Return ``(station_id, timestamp)`` for every stored station.

        The projection backs the list endpoint, which returns only the
        identifier and current timestamp of each station that has a stored
        snapshot (Requirement 5.4).

        Returns:
            A list of ``(station_id, timestamp)`` pairs; empty when no station
            has a stored snapshot (Requirement 5.6).
        """
        ...
