"""Unit tests for Metrics (GET) handler edge cases.

Covers:
- Empty store list → 200 with [] (Requirement 5.6)
- Malformed station_id on GET → 400 (Requirement 5.5)
"""

from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.metrics_handler import get_station, list_stations


def test_empty_store_list_returns_200_empty():
    """list_stations on an empty store returns 200 with body == []."""
    store = InMemoryStatisticsStore()
    result = list_stations(store)
    assert result.status_code == 200
    assert result.body == []


def test_malformed_station_id_returns_400():
    """get_station with a malformed station_id returns 400 with 'malformed' in body."""
    store = InMemoryStatisticsStore()
    result = get_station("INVALID!", store)
    assert result.status_code == 400
    assert "malformed" in result.body["error"]
