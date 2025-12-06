"""Tests for fastapi_loopguard.logging module."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from fastapi_loopguard.logging import (
    StructuredFormatter,
    configure_logging,
    log_blocking_event,
    logger,
)


class TestStructuredFormatter:
    """Tests for StructuredFormatter class."""

    def test_format_basic_message(self) -> None:
        """Test basic JSON output with required fields."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert "timestamp" in data
        assert data["level"] == "WARNING"
        assert data["logger"] == "test"
        assert data["message"] == "Test message"

    def test_format_with_extra_fields(self) -> None:
        """Test JSON output includes extra fields when present."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Blocking detected",
            args=(),
            exc_info=None,
        )
        # Add extra fields
        record.path = "/api/users"
        record.method = "GET"
        record.lag_ms = 150.5
        record.request_id = "abc123"
        record.blocking_count = 2

        output = formatter.format(record)
        data = json.loads(output)

        assert data["path"] == "/api/users"
        assert data["method"] == "GET"
        assert data["lag_ms"] == 150.5
        assert data["request_id"] == "abc123"
        assert data["blocking_count"] == 2

    def test_format_partial_extra_fields(self) -> None:
        """Test JSON output with only some extra fields."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Partial fields",
            args=(),
            exc_info=None,
        )
        record.lag_ms = 50.0
        # No path, method, request_id, blocking_count

        output = formatter.format(record)
        data = json.loads(output)

        assert data["lag_ms"] == 50.0
        assert "path" not in data
        assert "method" not in data

    def test_timestamp_is_iso_format(self) -> None:
        """Test timestamp is valid ISO format."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        # Should be parseable as ISO timestamp
        timestamp = data["timestamp"]
        assert "T" in timestamp  # ISO format has T separator
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z")


class TestConfigureLogging:
    """Tests for configure_logging function."""

    @pytest.fixture(autouse=True)
    def cleanup_handlers(self) -> None:
        """Remove handlers after each test."""
        yield
        logger.handlers.clear()

    def test_configure_with_defaults(self) -> None:
        """Test configuration with default values."""
        stream = StringIO()
        configure_logging(stream=stream)

        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_configure_structured_format(self) -> None:
        """Test structured JSON formatting."""
        stream = StringIO()
        configure_logging(structured=True, stream=stream)

        assert isinstance(logger.handlers[0].formatter, StructuredFormatter)

        # Verify JSON output
        logger.warning("Test message")
        output = stream.getvalue()
        data = json.loads(output.strip())
        assert data["message"] == "Test message"

    def test_configure_standard_format(self) -> None:
        """Test standard text formatting (default)."""
        stream = StringIO()
        configure_logging(structured=False, stream=stream)

        assert not isinstance(logger.handlers[0].formatter, StructuredFormatter)

        logger.warning("Test message")
        output = stream.getvalue()
        assert "Test message" in output
        assert "WARNING" in output

    def test_configure_custom_level(self) -> None:
        """Test custom log level."""
        stream = StringIO()
        configure_logging(level=logging.DEBUG, stream=stream)

        assert logger.level == logging.DEBUG

        logger.debug("Debug message")
        output = stream.getvalue()
        assert "Debug message" in output

    def test_configure_custom_stream(self) -> None:
        """Test output to custom stream."""
        custom_stream = StringIO()
        configure_logging(stream=custom_stream)

        logger.warning("Custom stream test")
        assert "Custom stream test" in custom_stream.getvalue()


class TestLogBlockingEvent:
    """Tests for log_blocking_event function."""

    @pytest.fixture(autouse=True)
    def setup_logger(self) -> None:
        """Set up logger with capturing handler."""
        self.stream = StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        yield
        logger.handlers.clear()

    def test_log_with_request_context(self) -> None:
        """Test logging with full request context."""
        log_blocking_event(
            lag_ms=150.5,
            path="/api/users",
            method="GET",
            request_id="abc123",
        )

        output = self.stream.getvalue()
        data = json.loads(output.strip())

        assert "blocked for 150.50ms during GET /api/users" in data["message"]
        assert data["lag_ms"] == 150.5
        assert data["path"] == "/api/users"
        assert data["method"] == "GET"
        assert data["request_id"] == "abc123"

    def test_log_without_request_context(self) -> None:
        """Test logging without request context."""
        log_blocking_event(lag_ms=100.0)

        output = self.stream.getvalue()
        data = json.loads(output.strip())

        assert "no active request" in data["message"]
        assert data["lag_ms"] == 100.0
        assert data["path"] is None

    def test_log_with_partial_context(self) -> None:
        """Test logging with only path and method."""
        log_blocking_event(
            lag_ms=75.25,
            path="/health",
            method="GET",
        )

        output = self.stream.getvalue()
        data = json.loads(output.strip())

        assert "GET /health" in data["message"]
        assert data["request_id"] is None

    def test_log_level_is_warning(self) -> None:
        """Test that blocking events are logged at WARNING level."""
        log_blocking_event(lag_ms=50.0, path="/test", method="POST")

        output = self.stream.getvalue()
        data = json.loads(output.strip())

        assert data["level"] == "WARNING"
