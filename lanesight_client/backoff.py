"""Exponential backoff scheduler for the LaneSight_Client.

Computes the delay before the next Submission_Attempt from the count of
consecutive failures, per Requirement 8.2 and the design "Backoff scheduler"
section:

    delay = min(2 * 2^(n-1), 60) seconds

for the ``n``-th consecutive failure (``n >= 1``). This yields the
non-decreasing, 60s-capped sequence::

    2, 4, 8, 16, 32, 60, 60, ...

Resetting is the caller's responsibility: on a successful Submission_Attempt
the consecutive-failure counter is reset to 0, so the next failure is again
counted as ``n = 1`` and produces a 2-second delay.
"""

from __future__ import annotations

# Backoff tuning constants (Requirement 8.2).
INITIAL_BACKOFF_SECONDS: float = 2.0
MAX_BACKOFF_SECONDS: float = 60.0


def next_backoff(consecutive_failures: int) -> float:
    """Return the backoff delay in seconds for the n-th consecutive failure.

    Args:
        consecutive_failures: The count ``n`` of consecutive failed
            Submission_Attempts, where ``n >= 1`` for the first failure after
            the last success. A value of ``0`` (no failures yet, i.e. just
            after a success) also returns the initial delay, so callers may
            reset the counter to ``0`` on success without special-casing the
            first subsequent failure.

    Returns:
        ``min(2 * 2^(n-1), 60)`` seconds as a float, capped at 60 seconds.

    Raises:
        ValueError: If ``consecutive_failures`` is negative.
    """
    if consecutive_failures < 0:
        raise ValueError("consecutive_failures must be non-negative")

    # Treat the "just reset" 0 case the same as the first failure (n = 1).
    n = consecutive_failures if consecutive_failures >= 1 else 1

    # Clamp the exponent before computing the power so an arbitrarily large
    # failure count (Req 8.3: no fixed maximum number of attempts) never
    # overflows. The result is capped at MAX_BACKOFF_SECONDS regardless, so any
    # exponent beyond the point the cap is reached yields the same value.
    growth_steps = min(n - 1, 64)

    delay = INITIAL_BACKOFF_SECONDS * (2 ** growth_steps)
    return float(min(delay, MAX_BACKOFF_SECONDS))


# Design references the private method name ``_next_backoff`` on
# ``LaneSightClient``; expose an alias so the client can delegate to this pure
# function without duplicating the logic.
_next_backoff = next_backoff
