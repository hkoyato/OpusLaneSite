"""Concrete-value unit tests for the LaneSight_Client exponential backoff scheduler.

These plain (non-Hypothesis) tests pin the exact backoff sequence and confirm
that the scheduler imposes no fixed maximum number of attempts: retries continue
indefinitely with the capped 60-second delay rather than raising or returning a
sentinel that would terminate retrying.

Validates: Requirements 8.2, 8.3
"""

from __future__ import annotations

import pytest

from lanesight_client.backoff import MAX_BACKOFF_SECONDS, next_backoff


def test_concrete_backoff_sequence() -> None:
    """Req 8.2: the first eight consecutive failures yield 2, 4, 8, 16, 32, 60, 60, 60.

    The delay doubles from 2 seconds and is capped at 60 seconds from the sixth
    failure onward.
    """
    sequence = [next_backoff(n) for n in range(1, 9)]
    assert sequence == [2, 4, 8, 16, 32, 60, 60, 60]


@pytest.mark.parametrize(
    ("consecutive_failures", "expected"),
    [
        (1, 2),
        (2, 4),
        (3, 8),
        (4, 16),
        (5, 32),
        (6, 60),
        (7, 60),
        (8, 60),
    ],
)
def test_individual_backoff_values(consecutive_failures: int, expected: float) -> None:
    """Each n-th consecutive failure maps to its exact expected delay (Req 8.2)."""
    assert next_backoff(consecutive_failures) == expected


def test_no_fixed_max_attempt_cap() -> None:
    """Req 8.3: no fixed maximum number of attempts is imposed.

    For arbitrarily large failure counts the scheduler keeps returning the
    capped 60-second delay. It never raises and never returns a sentinel that
    would stop retrying, so retries can continue indefinitely until the snapshot
    is published, discarded, or evicted.
    """
    for n in (9, 100, 1000, 100_000, 10_000_000):
        delay = next_backoff(n)
        assert delay == MAX_BACKOFF_SECONDS == 60
