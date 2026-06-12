"""Integration tests for HTTP method routing (Task 14.2).

Method routing enforcement is primarily the responsibility of the API Gateway
layer: ``infra/template.yaml`` defines only POST on the snapshot resource and
GET on the metrics resources. Any other HTTP method on those resources triggers
the ``DEFAULT_4XX`` GatewayResponse which returns ``405 Method Not Allowed``
before the request ever reaches the Lambda handler.

As a defense-in-depth measure, the Lambda entry points (``snapshot_handler``
and ``metrics_handler``) also validate the incoming HTTP method and return
``405`` for unexpected methods. This ensures correct behavior when the handler
is invoked directly (tests, local development, or a misconfigured gateway).

These integration tests verify:
    1. Calling ``snapshot_handler`` with a non-POST method (GET, PUT, DELETE,
       PATCH) returns HTTP 405.
    2. Calling ``metrics_handler`` with a non-GET method (POST, PUT, DELETE,
       PATCH) returns HTTP 405.
    3. The template.yaml declares exactly the expected methods on each resource,
       confirming the gateway-level enforcement contract.

Validates: Requirements 1.5, 5.7
"""

from __future__ import annotations

import json

import pytest
import yaml

from station_stats_api.lambda_handler import metrics_handler, snapshot_handler
from station_stats_api.memory_store import InMemoryStatisticsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """A fresh in-memory Statistics_Store for handler isolation."""
    return InMemoryStatisticsStore()


def _snapshot_event(method: str, station_id: str = "test_station") -> dict:
    """Build an API Gateway proxy event targeting the snapshot resource."""
    return {
        "httpMethod": method,
        "pathParameters": {"station_id": station_id},
        "body": json.dumps({
            "station_id": station_id,
            "timestamp": "2026-06-12T21:45:00Z",
            "vehicles_in_queue": 5,
            "vehicles_in_bay": 2,
            "active_lanes": 3,
            "average_queue_wait_minutes": 10.0,
            "average_inspection_minutes": 6.0,
            "estimated_public_wait_minutes": 15.0,
            "throughput_per_hour": 20,
            "slowest_lane_id": "lane_1",
            "confidence_score": 0.9,
        }),
        "isBase64Encoded": False,
    }


def _metrics_event(method: str, station_id: str | None = None) -> dict:
    """Build an API Gateway proxy event targeting the metrics resource."""
    event: dict = {
        "httpMethod": method,
        "body": None,
        "isBase64Encoded": False,
    }
    if station_id is not None:
        event["pathParameters"] = {"station_id": station_id}
    else:
        event["pathParameters"] = None
    return event


# ---------------------------------------------------------------------------
# 1. Non-POST on the snapshot resource returns 405 (Req 1.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
def test_snapshot_handler_rejects_non_post_methods(store, method):
    """Non-POST methods on the snapshot resource return 405 (Req 1.5).

    API Gateway enforces this at the gateway layer via the DEFAULT_4XX
    GatewayResponse. The handler provides defense-in-depth by checking the
    method itself.
    """
    event = _snapshot_event(method)
    response = snapshot_handler(event, store=store)

    assert response["statusCode"] == 405
    body = json.loads(response["body"])
    assert "not allowed" in body["error"].lower()


def test_snapshot_handler_accepts_post(store):
    """POST on the snapshot resource is accepted (baseline sanity check)."""
    event = _snapshot_event("POST")
    response = snapshot_handler(event, store=store)

    # 201 (stored) confirms POST is handled correctly.
    assert response["statusCode"] == 201


# ---------------------------------------------------------------------------
# 2. Non-GET on the metrics resource returns 405 (Req 5.7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_metrics_handler_rejects_non_get_methods_single(store, method):
    """Non-GET methods on the single-station metrics resource return 405 (Req 5.7).

    API Gateway enforces this at the gateway layer via the DEFAULT_4XX
    GatewayResponse. The handler provides defense-in-depth by checking the
    method itself.
    """
    event = _metrics_event(method, station_id="test_station")
    response = metrics_handler(event, store=store)

    assert response["statusCode"] == 405
    body = json.loads(response["body"])
    assert "not allowed" in body["error"].lower()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_metrics_handler_rejects_non_get_methods_list(store, method):
    """Non-GET methods on the station-list metrics resource return 405 (Req 5.7).

    API Gateway enforces this at the gateway layer via the DEFAULT_4XX
    GatewayResponse. The handler provides defense-in-depth by checking the
    method itself.
    """
    event = _metrics_event(method, station_id=None)
    response = metrics_handler(event, store=store)

    assert response["statusCode"] == 405
    body = json.loads(response["body"])
    assert "not allowed" in body["error"].lower()


def test_metrics_handler_accepts_get_single(store):
    """GET on the single-station metrics resource is accepted (baseline)."""
    event = _metrics_event("GET", station_id="test_station")
    response = metrics_handler(event, store=store)

    # 404 (no stored snapshot) confirms the GET path is handling normally.
    assert response["statusCode"] == 404


def test_metrics_handler_accepts_get_list(store):
    """GET on the station-list metrics resource is accepted (baseline)."""
    event = _metrics_event("GET", station_id=None)
    response = metrics_handler(event, store=store)

    # 200 with empty list confirms the GET path is handling normally.
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == []


# ---------------------------------------------------------------------------
# 3. Template defines exactly the expected methods per resource (gateway check)
# ---------------------------------------------------------------------------


def test_template_defines_only_post_on_snapshot_resource():
    """infra/template.yaml declares only POST on /stations/{station_id}/snapshot.

    This confirms the API Gateway contract that enforces method routing at the
    gateway layer: only POST is routed to the snapshot Lambda; all other
    methods trigger the DEFAULT_4XX GatewayResponse (405).

    Validates: Requirement 1.5
    """
    with open("infra/template.yaml", "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)

    resources = template["Resources"]
    snapshot_fn = resources["SnapshotFunction"]
    events = snapshot_fn["Properties"]["Events"]

    # Collect all methods defined for the snapshot function.
    methods = set()
    for event_def in events.values():
        props = event_def.get("Properties", {})
        methods.add(props.get("Method", "").upper())

    assert methods == {"POST"}, f"Expected only POST, got {methods}"

    # Verify the path matches the expected snapshot resource.
    paths = set()
    for event_def in events.values():
        props = event_def.get("Properties", {})
        paths.add(props.get("Path", ""))

    assert "/stations/{station_id}/snapshot" in paths


def test_template_defines_only_get_on_metrics_resources():
    """infra/template.yaml declares only GET on /stations and /stations/{station_id}.

    This confirms the API Gateway contract that enforces method routing at the
    gateway layer: only GET is routed to the metrics Lambda; all other methods
    trigger the DEFAULT_4XX GatewayResponse (405).

    Validates: Requirement 5.7
    """
    with open("infra/template.yaml", "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)

    resources = template["Resources"]
    metrics_fn = resources["MetricsFunction"]
    events = metrics_fn["Properties"]["Events"]

    # Collect all methods defined for the metrics function.
    methods = set()
    for event_def in events.values():
        props = event_def.get("Properties", {})
        methods.add(props.get("Method", "").upper())

    assert methods == {"GET"}, f"Expected only GET, got {methods}"

    # Verify both expected paths are present.
    paths = set()
    for event_def in events.values():
        props = event_def.get("Properties", {})
        paths.add(props.get("Path", ""))

    assert "/stations/{station_id}" in paths
    assert "/stations" in paths


def test_template_defines_default_4xx_as_405():
    """infra/template.yaml configures DEFAULT_4XX GatewayResponse with status 405.

    This is the mechanism that returns 'Method Not Allowed' for any HTTP method
    not explicitly defined on a resource.

    Validates: Requirements 1.5, 5.7
    """
    with open("infra/template.yaml", "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)

    resources = template["Resources"]
    api = resources["StationStatsApi"]
    gateway_responses = api["Properties"]["GatewayResponses"]

    default_4xx = gateway_responses["DEFAULT_4XX"]
    assert default_4xx["StatusCode"] == 405
