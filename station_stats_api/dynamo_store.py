"""DynamoDB-backed :class:`StatisticsStore` for the Station_Stats_API.

This module provides :class:`DynamoStatisticsStore`, the production persistence
adapter that satisfies the :class:`station_stats_api.store.StatisticsStore`
protocol against an Amazon DynamoDB table. The in-memory fake (task 3.2) is used
by property tests; this adapter encapsulates the equivalent last-write-wins
logic as a single conditional ``PutItem`` so storage logic is verified against
the fake while the real backend behaves identically (see design.md
"Statistics_Store (DynamoDB adapter)" and "DynamoDB table: StationStatistics").

Table shape (``StationStatistics``)
-----------------------------------
- ``station_id`` (S) — partition key; exactly one item per station, no sort key.
- ``timestamp`` (S) — the ISO 8601 timestamp string exactly as submitted,
  preserved and returned to consumers unchanged (Req 1.3, 1.4, 5.3).
- ``timestamp_utc`` (S) — the UTC-normalized ISO 8601 instant, used only for
  ordering (Req 4.2).
- ``snapshot`` (M) — the full Glossary-field snapshot map as stored.

Capacity
--------
The table uses on-demand billing (``PAY_PER_REQUEST``) so concurrent writes
across up to 100+ station partitions need no provisioning change (Req 6.3, 4.6).
Use :func:`build_table_definition` to obtain the ``create_table`` arguments.

boto3 import policy
-------------------
``boto3``/``botocore`` are imported lazily inside the methods/constructor that
need them, so importing this module never requires boto3 to be installed and
never makes an AWS call at import time. The class is exercised elsewhere with
mocks/stubs; the rest of the test suite runs without AWS or boto3 present.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .store import PutOutcome
from .timestamps import to_utc_instant

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    pass

#: Default DynamoDB table name for the Statistics_Store.
DEFAULT_TABLE_NAME = "StationStatistics"

#: Stored attribute names.
ATTR_STATION_ID = "station_id"
ATTR_TIMESTAMP = "timestamp"
ATTR_TIMESTAMP_UTC = "timestamp_utc"
ATTR_SNAPSHOT = "snapshot"

#: Last-write-wins condition: store iff no item exists yet OR the incoming
#: UTC-normalized instant is strictly later than the stored one (Req 4.2, 4.3).
_CONDITION_EXPRESSION = (
    f"attribute_not_exists({ATTR_STATION_ID}) OR :new_utc > {ATTR_TIMESTAMP_UTC}"
)


def build_table_definition(table_name: str = DEFAULT_TABLE_NAME) -> dict[str, Any]:
    """Return ``create_table`` arguments for the ``StationStatistics`` table.

    The table uses a single partition key ``station_id`` (no sort key) so it
    holds exactly the current snapshot per station, and on-demand billing
    (``PAY_PER_REQUEST``) so write throughput scales with the number of active
    stations without a provisioning change (Req 6.3).

    Args:
        table_name: The DynamoDB table name to create.

    Returns:
        A mapping suitable for ``dynamodb_client.create_table(**definition)`` or
        ``dynamodb_resource.create_table(**definition)``.
    """
    return {
        "TableName": table_name,
        "KeySchema": [
            {"AttributeName": ATTR_STATION_ID, "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": ATTR_STATION_ID, "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def _normalize(value: Any) -> Any:
    """Recursively convert DynamoDB ``Decimal`` values back to int/float.

    The DynamoDB resource API marshals numbers to :class:`decimal.Decimal`.
    Normalizing both sides lets us compare a stored snapshot against an incoming
    one for the duplicate check without spurious ``Decimal`` vs ``float``
    mismatches.
    """
    if isinstance(value, Decimal):
        # Preserve integers as int; everything else as float.
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


class DynamoStatisticsStore:
    """DynamoDB-backed :class:`~station_stats_api.store.StatisticsStore`.

    Wraps a boto3 DynamoDB *table resource* and implements last-write-wins
    storage via a single conditional ``PutItem``. The table resource can be
    injected directly (for tests/mocks) or constructed lazily from a table name
    and an optional boto3 DynamoDB *service resource*.

    No AWS calls are made during construction, and ``boto3`` is imported lazily
    so importing this module does not require boto3 to be installed.
    """

    def __init__(
        self,
        table: Any | None = None,
        *,
        table_name: str = DEFAULT_TABLE_NAME,
        dynamodb_resource: Any | None = None,
    ) -> None:
        """Create the store.

        Args:
            table: A boto3 DynamoDB *table* resource
                (e.g. ``boto3.resource("dynamodb").Table("StationStatistics")``).
                When provided, it is used directly and no boto3 import occurs.
            table_name: The table name to bind when ``table`` is not given.
            dynamodb_resource: An optional boto3 DynamoDB *service resource* used
                to obtain the table when ``table`` is not given. When omitted,
                ``boto3.resource("dynamodb")`` is created lazily.

        Raises:
            RuntimeError: If a table must be constructed but ``boto3`` is not
                importable.
        """
        if table is not None:
            self._table = table
            return

        resource = dynamodb_resource
        if resource is None:
            try:
                import boto3  # local, lazy import
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "boto3 is required to construct DynamoStatisticsStore from a "
                    "table name; install boto3 or inject a table resource."
                ) from exc
            resource = boto3.resource("dynamodb")

        # .Table(name) returns a lazy handle and does not make an AWS call.
        self._table = resource.Table(table_name)

    def put_if_newer(self, snapshot: dict) -> PutOutcome:
        """Store ``snapshot`` under last-write-wins semantics (Req 4.1–4.3, 8.8).

        Performs a conditional ``PutItem`` that succeeds only when no item exists
        for the ``station_id`` or the incoming UTC instant is strictly later than
        the stored one. When the condition fails, the existing item is read to
        distinguish an idempotent duplicate from a retained-existing outcome.

        Args:
            snapshot: A validated, Glossary-field-only snapshot mapping that
                includes ``station_id`` and ``timestamp``.

        Returns:
            :attr:`PutOutcome.STORED` when the snapshot became current,
            :attr:`PutOutcome.DUPLICATE` when the same instant and content were
            already stored, or :attr:`PutOutcome.RETAINED_EXISTING` when an
            equal-or-later snapshot was retained instead.

        Raises:
            botocore.exceptions.ClientError: For any storage error other than the
                expected conditional-check failure. The Snapshot handler maps
                such errors to HTTP 503 (Req 10.2).
        """
        from botocore.exceptions import ClientError  # local, lazy import

        station_id = snapshot[ATTR_STATION_ID]
        submitted_ts = snapshot[ATTR_TIMESTAMP]
        new_utc = to_utc_instant(submitted_ts).isoformat()

        item = {
            ATTR_STATION_ID: station_id,
            ATTR_TIMESTAMP: submitted_ts,
            ATTR_TIMESTAMP_UTC: new_utc,
            ATTR_SNAPSHOT: snapshot,
        }

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=_CONDITION_EXPRESSION,
                ExpressionAttributeValues={":new_utc": new_utc},
            )
            return PutOutcome.STORED
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ConditionalCheckFailedException":
                # Storage error — surfaced to the handler, mapped to 503 (Req 10.2).
                raise
            # The incoming instant is not strictly later than the stored one.
            return self._resolve_condition_failure(station_id, new_utc, snapshot)

    def _resolve_condition_failure(
        self, station_id: str, new_utc: str, snapshot: dict
    ) -> PutOutcome:
        """Classify a condition-check failure as DUPLICATE or RETAINED_EXISTING.

        Reads the current item and returns :attr:`PutOutcome.DUPLICATE` when the
        stored item denotes the same UTC instant and the same snapshot content
        (an idempotent resubmission, Req 8.8); otherwise returns
        :attr:`PutOutcome.RETAINED_EXISTING` (Req 4.3).
        """
        existing = self._get_item(station_id)
        if (
            existing is not None
            and existing.get(ATTR_TIMESTAMP_UTC) == new_utc
            and _normalize(existing.get(ATTR_SNAPSHOT)) == _normalize(snapshot)
        ):
            return PutOutcome.DUPLICATE
        return PutOutcome.RETAINED_EXISTING

    def get(self, station_id: str) -> dict | None:
        """Return the current snapshot for ``station_id`` or ``None`` (Req 5.2)."""
        item = self._get_item(station_id)
        if item is None:
            return None
        stored = item.get(ATTR_SNAPSHOT)
        if stored is None:
            return None
        return _normalize(stored)

    def _get_item(self, station_id: str) -> dict | None:
        """Fetch the raw stored item for ``station_id`` or ``None``."""
        response = self._table.get_item(Key={ATTR_STATION_ID: station_id})
        return response.get("Item")

    def list_index(self) -> list[tuple[str, str]]:
        """Return ``(station_id, timestamp)`` for every stored station (Req 5.4).

        Reads only the ``station_id`` and ``timestamp`` attributes via a
        projection expression to keep the list response small, paginating across
        the full table scan.

        Returns:
            A list of ``(station_id, timestamp)`` pairs; empty when no station
            has a stored snapshot (Req 5.6).
        """
        # "timestamp" is a DynamoDB reserved word, so alias it.
        scan_kwargs: dict[str, Any] = {
            "ProjectionExpression": f"{ATTR_STATION_ID}, #ts",
            "ExpressionAttributeNames": {"#ts": ATTR_TIMESTAMP},
        }
        index: list[tuple[str, str]] = []
        while True:
            response = self._table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                index.append((item[ATTR_STATION_ID], item[ATTR_TIMESTAMP]))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        return index
