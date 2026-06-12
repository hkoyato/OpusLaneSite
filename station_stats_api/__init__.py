"""Station_Stats_API package.

AWS-hosted ingestion and retrieval service that collects Station_Metric_Snapshots
from every Opus LaneSight instance, stores the most recent snapshot per station,
and serves them to internal and public consumers. See the station-stats-api
design document for the full component breakdown.
"""

from .http_result import (
    HTTP_BAD_REQUEST,
    HTTP_CREATED,
    HTTP_FORBIDDEN,
    HTTP_INTERNAL_SERVER_ERROR,
    HTTP_METHOD_NOT_ALLOWED,
    HTTP_NOT_FOUND,
    HTTP_OK,
    HTTP_PAYLOAD_TOO_LARGE,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_UNAUTHORIZED,
    HTTP_UNPROCESSABLE_ENTITY,
    PUT_OUTCOME_STATUS,
    HttpResult,
    JsonBody,
)
from .logging_support import (
    REDACTED_PLACEHOLDER,
    REJECTION_FORBIDDEN,
    REJECTION_INTERNAL_ERROR,
    REJECTION_MALFORMED_JSON,
    REJECTION_MALFORMED_STATION_ID,
    REJECTION_METHOD_NOT_ALLOWED,
    REJECTION_NOT_FOUND,
    REJECTION_PAYLOAD_TOO_LARGE,
    REJECTION_STORAGE_ERROR,
    REJECTION_UNAUTHENTICATED,
    REJECTION_VALIDATION_FAILED,
    STATION_ID_ABSENT,
    STATION_ID_UNPARSEABLE,
    build_log_entry,
    emit_log,
    redact,
)
from .memory_store import (
    InMemoryStatisticsStore,
)
from .metrics_handler import (
    get_station,
    list_stations,
)
from .dynamo_store import (
    DEFAULT_TABLE_NAME,
    DynamoStatisticsStore,
    build_table_definition,
)
from .lambda_handler import (
    authorizer_handler,
    metrics_handler as metrics_lambda_handler,
    snapshot_handler as snapshot_lambda_handler,
)
from .snapshot_handler import (
    handle_snapshot,
)
from .store import (
    PutOutcome,
    StatisticsStore,
)
from .timestamps import (
    InvalidTimestampError,
    is_valid_timestamp,
    to_utc_instant,
    try_to_utc_instant,
)
from .validation import (
    GLOSSARY_FIELDS,
    INTEGER_FIELDS,
    MINUTE_FIELDS,
    ValidationResult,
    is_valid_station_id,
    validate_snapshot,
)

__all__ = [
    # Shared HTTP result types and status-mapping constants (task 1.1)
    "HttpResult",
    "JsonBody",
    "PUT_OUTCOME_STATUS",
    "HTTP_OK",
    "HTTP_CREATED",
    "HTTP_BAD_REQUEST",
    "HTTP_UNAUTHORIZED",
    "HTTP_FORBIDDEN",
    "HTTP_NOT_FOUND",
    "HTTP_METHOD_NOT_ALLOWED",
    "HTTP_PAYLOAD_TOO_LARGE",
    "HTTP_UNPROCESSABLE_ENTITY",
    "HTTP_INTERNAL_SERVER_ERROR",
    "HTTP_SERVICE_UNAVAILABLE",
    # Timestamp normalization (task 2.1)
    "InvalidTimestampError",
    "is_valid_timestamp",
    "to_utc_instant",
    "try_to_utc_instant",
    # Snapshot validation (task 2.2)
    "ValidationResult",
    "validate_snapshot",
    "is_valid_station_id",
    "GLOSSARY_FIELDS",
    "INTEGER_FIELDS",
    "MINUTE_FIELDS",
    # Statistics_Store contract (task 3.1)
    "PutOutcome",
    "StatisticsStore",
    # Snapshot (POST) handler (task 4.1)
    "handle_snapshot",
    # DynamoDB-backed Statistics_Store (task 3.6)
    "DynamoStatisticsStore",
    "build_table_definition",
    "DEFAULT_TABLE_NAME",
    # In-memory Statistics_Store fake (task 3.2)
    "InMemoryStatisticsStore",
    # Metrics (GET) handler (task 5.1)
    "get_station",
    "list_stations",
    # Lambda event adapter entry points (task 8.2)
    "authorizer_handler",
    "snapshot_lambda_handler",
    "metrics_lambda_handler",
    # Logging and observability (task 6.1)
    "build_log_entry",
    "redact",
    "emit_log",
    "STATION_ID_ABSENT",
    "STATION_ID_UNPARSEABLE",
    "REDACTED_PLACEHOLDER",
    "REJECTION_MALFORMED_JSON",
    "REJECTION_VALIDATION_FAILED",
    "REJECTION_PAYLOAD_TOO_LARGE",
    "REJECTION_UNAUTHENTICATED",
    "REJECTION_FORBIDDEN",
    "REJECTION_METHOD_NOT_ALLOWED",
    "REJECTION_MALFORMED_STATION_ID",
    "REJECTION_NOT_FOUND",
    "REJECTION_STORAGE_ERROR",
    "REJECTION_INTERNAL_ERROR",
]
