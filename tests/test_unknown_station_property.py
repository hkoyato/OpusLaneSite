"""Property-based test for unknown well-formed station lookups returning 404.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the ``get_station`` metrics handler. The
unit under test is :func:`station_stats_api.metrics_handler.get_station` backed
by an empty :class:`station_stats_api.memory_store.InMemoryStatisticsStore`.

For any well-formed ``Station_Identifier`` that has no stored snapshot, a GET
for that station returns HTTP 404 with a body indicating that no statistics
exist for the requested station.

Validates: Requirements 5.2
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.metrics_handler import get_station


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Well-formed station_id: 1–64 characters from [a-z0-9_-] (Requirement 2.1).
_STATION_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_-"

well_formed_station_ids = st.text(
    alphabet=_STATION_ID_ALPHABET,
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Property 9: Unknown well-formed stations return 404
# ---------------------------------------------------------------------------
# Feature: station-stats-api, Property 9: Unknown well-formed stations return 404


@settings(max_examples=100)
@given(station_id=well_formed_station_ids)
def test_unknown_well_formed_stations_return_404(station_id: str) -> None:
    """**Validates: Requirements 5.2**

    For any well-formed Station_Identifier that has no stored snapshot,
    calling get_station on an empty store returns HTTP 404 with a body
    indicating that no statistics exist for the requested station.
    """
    store = InMemoryStatisticsStore()

    result = get_station(station_id, store)

    assert result.status_code == 404
    assert "error" in result.body
    assert "no statistics" in result.body["error"].lower()
