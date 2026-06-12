"""Property-based test for the Connectivity_Notification state reducer.

Uses Hypothesis to verify Property 17 from the station-stats-api design
document: the derived ``Connectivity_Notification`` state is a pure function of
the latest submission event plus the current ``Pending_Snapshot_Buffer`` count.
The component under test, ``lanesight_client.notification``, performs no I/O and
holds no state, so the property runs headless and cheaply across many inputs.

The reducer collapses the richer submission outcomes / HTTP statuses into the
operator-facing distinctions that actually change what is shown:

- ``AUTH`` event (HTTP 401/403) -> visible, ``AUTH`` category, distinct from an
  outage (Req 9.5).
- ``OUTAGE`` event (timeout / network error / HTTP 5xx) -> visible, ``OUTAGE``
  category (Req 9.1).
- ``EVICTION`` -> visible, ``PERMANENT_DROP`` category (Req 9.7).
- ``NOT_CONFIGURED`` -> visible, ``NOT_CONFIGURED`` category (Req 7.6).
- ``SUCCESS`` (201 / duplicate 200) -> cleared / hidden, ``NONE`` category
  (publishing resumed; Req 9.3).
- While visible, the state carries the provided buffer count (Req 9.2).

Validates: Requirements 9.1, 9.2, 9.5, 9.7
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from lanesight_client.models import SubmitOutcome
from lanesight_client.notification import (
    NotificationCategory,
    NotificationEvent,
    event_from_status,
    reduce_notification,
)

# The expected (visible, category) outcome for each latest event, derived
# directly from the design's notification semantics rather than the module's
# internal tables, so the test is an independent oracle.
_EXPECTED: dict[NotificationEvent, tuple[bool, NotificationCategory]] = {
    NotificationEvent.AUTH: (True, NotificationCategory.AUTH),
    NotificationEvent.OUTAGE: (True, NotificationCategory.OUTAGE),
    NotificationEvent.EVICTION: (True, NotificationCategory.PERMANENT_DROP),
    NotificationEvent.NOT_CONFIGURED: (True, NotificationCategory.NOT_CONFIGURED),
    NotificationEvent.SUCCESS: (False, NotificationCategory.NONE),
}


# Feature: station-stats-api, Property 17: Notification state derives from the latest outcome and buffer
@settings(max_examples=200, deadline=None)
@given(
    event=st.sampled_from(list(NotificationEvent)),
    buffer_count=st.integers(min_value=0, max_value=10_000),
)
def test_notification_state_derives_from_latest_outcome_and_buffer(
    event: NotificationEvent, buffer_count: int
) -> None:
    """For any latest event and non-negative buffer count, the derived state
    matches the spec: AUTH -> visible/AUTH (distinct from outage; Req 9.5),
    OUTAGE -> visible/OUTAGE (Req 9.1), EVICTION -> visible/PERMANENT_DROP
    (Req 9.7), NOT_CONFIGURED -> visible/NOT_CONFIGURED, SUCCESS -> hidden/NONE
    (resumed). While visible the state carries the provided buffer count
    (Req 9.2), and the AUTH copy is distinct from the OUTAGE copy (Req 9.5).
    """
    state = reduce_notification(event, buffer_count)

    expected_visible, expected_category = _EXPECTED[event]
    assert state.visible is expected_visible
    assert state.category is expected_category

    # The buffer count is always carried through unchanged (Req 9.2); while the
    # notice is visible the GUI uses it to display a live pending count.
    assert state.buffer_count == buffer_count

    # SUCCESS clears the notice (publishing resumed; Req 9.3), every other event
    # surfaces a visible warning.
    if event is NotificationEvent.SUCCESS:
        assert state.visible is False
        assert state.category is NotificationCategory.NONE
    else:
        assert state.visible is True
        assert state.category is not NotificationCategory.NONE

    # Auth failures are reported as an authentication/authorization problem
    # distinct from a network outage: both label and message must differ from
    # the outage copy (Req 9.5).
    if event is NotificationEvent.AUTH:
        outage = reduce_notification(NotificationEvent.OUTAGE, buffer_count)
        assert state.label != outage.label
        assert state.message != outage.message


# Status codes that classify as an outage when no overriding signal is present.
_FIVE_XX = st.integers(min_value=500, max_value=599)
_AUTH_STATUS = st.sampled_from([401, 403])
_SUCCESS_STATUS = st.sampled_from([200, 201, 204])


# Feature: station-stats-api, Property 17: Notification state derives from the latest outcome and buffer
@settings(max_examples=200, deadline=None)
@given(
    http_status=st.one_of(
        st.none(),
        _AUTH_STATUS,
        _FIVE_XX,
        _SUCCESS_STATUS,
        st.integers(min_value=400, max_value=499),
    ),
    timed_out=st.booleans(),
    network_error=st.booleans(),
    evicted=st.booleans(),
    configured=st.booleans(),
    outcome=st.one_of(st.none(), st.sampled_from(list(SubmitOutcome))),
)
def test_event_from_status_maps_concrete_results(
    http_status: int | None,
    timed_out: bool,
    network_error: bool,
    evicted: bool,
    configured: bool,
    outcome: SubmitOutcome | None,
) -> None:
    """``event_from_status`` maps concrete submission results to the salient
    event in the design's precedence order: not-configured (Req 7.6) and
    eviction (Req 9.7) outrank transport/status; PUBLISHED/DUPLICATE and 2xx
    clear; 401/403 -> AUTH (Req 9.5); timeout/network/5xx -> OUTAGE (Req 9.1).
    The produced event then reduces to a state consistent with Property 17.
    """
    event = event_from_status(
        outcome=outcome,
        http_status=http_status,
        timed_out=timed_out,
        network_error=network_error,
        evicted=evicted,
        configured=configured,
    )

    # Verify the documented precedence as an independent oracle.
    if not configured:
        assert event is NotificationEvent.NOT_CONFIGURED
    elif evicted:
        assert event is NotificationEvent.EVICTION
    elif outcome in (SubmitOutcome.PUBLISHED, SubmitOutcome.DUPLICATE):
        assert event is NotificationEvent.SUCCESS
    elif http_status in (401, 403):
        assert event is NotificationEvent.AUTH
    elif timed_out or network_error:
        assert event is NotificationEvent.OUTAGE
    elif http_status is not None and 500 <= http_status <= 599:
        assert event is NotificationEvent.OUTAGE
    elif http_status is not None and 200 <= http_status < 300:
        assert event is NotificationEvent.SUCCESS
    else:
        # Unexpected/unclassified failures never silently hide the notice.
        assert event is NotificationEvent.OUTAGE

    # Whatever event is produced, it must reduce to a coherent Property 17 state.
    state = reduce_notification(event, buffer_count=0)
    expected_visible, expected_category = _EXPECTED[event]
    assert state.visible is expected_visible
    assert state.category is expected_category
