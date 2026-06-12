"""Smoke tests for routing and TLS policy (Task 14.7).

These are single-execution concrete-example tests that verify:

1. POST accepts a valid body under 16KB through the Lambda adapter (snapshot_handler).
2. A body at exactly 16KB is NOT rejected for size (proceeds to parse/validate).
3. If a custom domain is defined in infra/template.yaml, it enforces HTTPS-only
   via TLS_1_2 security policy and no HTTP endpoint resource exists.
4. A valid POST event submitted to snapshot_handler succeeds end-to-end (201).

These tests exercise the Lambda adapter (snapshot_handler) and the IaC template
locally without requiring a deployed AWS environment.

Validates: Requirements 1.1, 3.4
"""

from __future__ import annotations

import json

import pytest
import yaml

from station_stats_api.lambda_handler import snapshot_handler
from station_stats_api.memory_store import InMemoryStatisticsStore
from station_stats_api.snapshot_handler import MAX_BODY_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_snapshot_dict(station_id: str = "smoke_station_01") -> dict:
    """Return a minimal valid Station_Metric_Snapshot."""
    return {
        "station_id": station_id,
        "timestamp": "2026-06-12T21:45:00Z",
        "vehicles_in_queue": 9,
        "vehicles_in_bay": 3,
        "active_lanes": 3,
        "average_queue_wait_minutes": 14.2,
        "average_inspection_minutes": 6.4,
        "estimated_public_wait_minutes": 18.0,
        "throughput_per_hour": 28,
        "slowest_lane_id": "lane_2",
        "confidence_score": 0.82,
    }


def _post_event(body_str: str, station_id: str = "smoke_station_01") -> dict:
    """Build an API Gateway proxy event for POST /stations/{station_id}/snapshot."""
    return {
        "httpMethod": "POST",
        "pathParameters": {"station_id": station_id},
        "body": body_str,
        "isBase64Encoded": False,
    }


@pytest.fixture
def store():
    """A fresh in-memory Statistics_Store."""
    return InMemoryStatisticsStore()


# ---------------------------------------------------------------------------
# 1. POST accepts a valid body under 16KB -> 201 (Req 1.1)
# ---------------------------------------------------------------------------


def test_post_accepts_valid_body_under_16kb(store):
    """A valid snapshot body well under 16KB is accepted via snapshot_handler.

    Validates: Requirement 1.1
    """
    snapshot = _valid_snapshot_dict()
    body_str = json.dumps(snapshot)
    # Sanity: confirm the body is under 16KB.
    assert len(body_str.encode()) < MAX_BODY_BYTES

    event = _post_event(body_str)
    response = snapshot_handler(event, store=store)

    assert response["statusCode"] == 201
    resp_body = json.loads(response["body"])
    assert resp_body["station_id"] == "smoke_station_01"
    assert resp_body["timestamp"] == "2026-06-12T21:45:00Z"


# ---------------------------------------------------------------------------
# 2. POST accepts body at exactly 16KB (not rejected for size) (Req 1.1)
# ---------------------------------------------------------------------------


def test_post_accepts_body_at_exactly_16kb(store):
    """A body exactly at the 16KB limit is NOT rejected for size.

    The body is padded to exactly 16*1024 bytes using an extra field. Since the
    size check passes, the body proceeds to the parse/validate path. The extra
    padding field is stripped on storage (Req 2.7), so a valid snapshot with
    padding results in a successful 201.

    Validates: Requirement 1.1
    """
    snapshot = _valid_snapshot_dict()
    # Build the body with a placeholder pad first, then adjust to hit exact size.
    snapshot["_pad"] = ""
    shell_bytes = json.dumps(snapshot).encode()
    # The empty-pad body has len(shell_bytes). We need to fill "_pad" so that
    # the total is exactly MAX_BODY_BYTES. Each added character to pad adds 1
    # byte in the JSON output (ASCII content, no escaping needed for 'x').
    pad_len = MAX_BODY_BYTES - len(shell_bytes)
    assert pad_len > 0, "Base snapshot already too large for this test"

    snapshot["_pad"] = "x" * pad_len
    body_bytes = json.dumps(snapshot).encode()
    assert len(body_bytes) == MAX_BODY_BYTES

    event = _post_event(body_bytes.decode())
    response = snapshot_handler(event, store=store)

    # Must NOT be 413 — the body at exactly the limit passes the size check.
    assert response["statusCode"] != 413
    # The body is valid JSON with valid snapshot fields, so it should store.
    assert response["statusCode"] == 201


# ---------------------------------------------------------------------------
# 3. Custom domain enforces HTTPS-only in template (Req 3.4)
# ---------------------------------------------------------------------------


def test_custom_domain_enforces_https_only_in_template():
    """If a custom domain is defined in infra/template.yaml, it enforces TLS_1_2.

    API Gateway HTTPS REST APIs never expose an HTTP (plaintext) listener. The
    default execute-api endpoint is HTTPS-only by AWS design. When a custom
    domain is configured, the template pins SecurityPolicy to TLS_1_2 and does
    not create any HTTP endpoint resource.

    This test parses the template and asserts:
      - The ApiDomainName resource (if present) uses SecurityPolicy: TLS_1_2.
      - No resource in the template provisions an HTTP (non-TLS) endpoint.

    Note: API Gateway by design never exposes a plaintext HTTP endpoint. There
    is no mechanism in the REST API type to create one. This test documents and
    verifies that contract in the IaC definition.

    Validates: Requirement 3.4
    """
    with open("infra/template.yaml", "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)

    resources = template["Resources"]

    # If custom domain resource exists, verify TLS policy.
    if "ApiDomainName" in resources:
        domain_props = resources["ApiDomainName"]["Properties"]
        assert domain_props["SecurityPolicy"] == "TLS_1_2", (
            "Custom domain must enforce TLS_1_2 security policy"
        )
        # Verify it uses REGIONAL endpoint (no edge, consistent with design).
        endpoint_config = domain_props.get("EndpointConfiguration", {})
        types = endpoint_config.get("Types", [])
        assert "REGIONAL" in types

    # Verify no resource creates an HTTP (non-TLS) endpoint.
    # API Gateway REST APIs (AWS::Serverless::Api / AWS::ApiGateway::RestApi)
    # are HTTPS-only by design. Verify there is no resource that could expose
    # HTTP — e.g., no HttpApi (which supports HTTP protocol) and no explicit
    # HTTP listener resource.
    http_resources = []
    for name, resource in resources.items():
        resource_type = resource.get("Type", "")
        # AWS::Serverless::HttpApi and AWS::ApiGatewayV2::Api can expose HTTP.
        if resource_type in (
            "AWS::Serverless::HttpApi",
            "AWS::ApiGatewayV2::Api",
        ):
            http_resources.append(name)

    assert http_resources == [], (
        f"Template should not expose HTTP endpoints; found: {http_resources}"
    )


# ---------------------------------------------------------------------------
# 4. Routing: POST to snapshot_handler succeeds end-to-end -> 201 (Req 1.1)
# ---------------------------------------------------------------------------


def test_routing_post_snapshot_succeeds(store):
    """A valid POST event submitted to snapshot_handler returns 201.

    Confirms the POST route works end-to-end through the Lambda adapter:
    event parsing -> body extraction -> handle_snapshot -> 201 proxy response.

    Validates: Requirement 1.1
    """
    snapshot = _valid_snapshot_dict(station_id="route_test_station")
    body_str = json.dumps(snapshot)

    event = _post_event(body_str, station_id="route_test_station")
    response = snapshot_handler(event, store=store)

    assert response["statusCode"] == 201
    resp_body = json.loads(response["body"])
    assert resp_body["station_id"] == "route_test_station"

    # Verify the snapshot was actually stored.
    stored = store.get("route_test_station")
    assert stored is not None
    assert stored["station_id"] == "route_test_station"
    assert stored["vehicles_in_queue"] == 9
