"""Property-based test for the LaneSight_Client exponential backoff scheduler.

Uses Hypothesis to verify the universal correctness property defined in the
station-stats-api design document for the backoff scheduler. The function under
test, ``lanesight_client.backoff.next_backoff``, is pure (no I/O, no Qt), so the
test runs headless and cheaply across many generated inputs.

Validates: Requirements 8.2
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.backoff import (
    MAX_BACKOFF_SECONDS,
    next_backoff,
)


def _expected_backoff(n: int) -> float:
    """Reference formula: min(2 * 2^(n-1), 60) seconds for the n-th failure."""
    return float(min(2 * 2 ** (n - 1), 60))


# Feature: station-stats-api, Property 14: Exponential backoff doubles from 2s and caps at 60s
@settings(max_examples=200)
@given(n=st.integers(min_value=1, max_value=100))
def test_backoff_doubles_from_2s_and_caps_at_60s(n: int) -> None:
    """For any n >= 1, next_backoff(n) == min(2 * 2^(n-1), 60); the sequence is
    non-decreasing in n and never exceeds 60 seconds.
    """
    delay = next_backoff(n)

    # Exact formula match.
    assert delay == _expected_backoff(n)

    # Cap invariant: never exceeds 60 seconds.
    assert delay <= MAX_BACKOFF_SECONDS

    # Monotonic non-decreasing between n and n + 1.
    assert next_backoff(n + 1) >= delay
