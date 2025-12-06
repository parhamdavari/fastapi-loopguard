"""Structured logging for LoopGuard events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("fastapi_loopguard")


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, "path"):
            log_data["path"] = record.path
        if hasattr(record, "method"):
            log_data["method"] = record.method
        if hasattr(record, "lag_ms"):
            log_data["lag_ms"] = record.lag_ms
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "blocking_count"):
            log_data["blocking_count"] = record.blocking_count

        return json.dumps(log_data)


def configure_logging(
    level: int = logging.INFO,
    structured: bool = False,
    stream: Any = None,
) -> None:
    """Configure logging for LoopGuard.

    Args:
        level: The logging level (default INFO).
        structured: If True, use JSON formatting.
        stream: Output stream (default stderr).
    """
    handler = logging.StreamHandler(stream or sys.stderr)

    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    logger.addHandler(handler)
    logger.setLevel(level)


def log_blocking_event(
    lag_ms: float,
    path: str | None = None,
    method: str | None = None,
    request_id: str | None = None,
) -> None:
    """Log a blocking event with structured data.

    Args:
        lag_ms: The blocking duration in milliseconds.
        path: The request path (if available).
        method: The HTTP method (if available).
        request_id: The request ID (if available).
    """
    extra = {
        "lag_ms": lag_ms,
        "path": path,
        "method": method,
        "request_id": request_id,
    }

    if path:
        logger.warning(
            "Event loop blocked for %.2fms during %s %s",
            lag_ms,
            method,
            path,
            extra=extra,
        )
    else:
        logger.warning(
            "Event loop blocked for %.2fms (no active request)",
            lag_ms,
            extra=extra,
        )
