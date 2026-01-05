"""Tests for enforcement mode feature."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware
from fastapi_loopguard.context import get_registry

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def clear_registry() -> Generator[None, None, None]:
    """Clear the request registry before and after each test."""
    get_registry().clear()
    yield
    get_registry().clear()


class TestEnforcementModeConfig:
    """Tests for enforcement mode configuration."""

    def test_default_enforcement_mode_is_warn(self) -> None:
        """Test that default enforcement mode is 'warn'."""
        config = LoopGuardConfig()
        assert config.enforcement_mode == "warn"

    def test_valid_enforcement_modes(self) -> None:
        """Test that all valid enforcement modes are accepted."""
        for mode in ["log", "warn", "strict"]:
            config = LoopGuardConfig(enforcement_mode=mode)
            assert config.enforcement_mode == mode

    def test_invalid_enforcement_mode_raises(self) -> None:
        """Test that invalid enforcement mode raises ValueError."""
        with pytest.raises(ValueError, match="enforcement_mode must be one of"):
            LoopGuardConfig(enforcement_mode="invalid")

    def test_invalid_enforcement_mode_error_message(self) -> None:
        """Test that error message includes the invalid value."""
        with pytest.raises(ValueError, match="got 'bad_mode'"):
            LoopGuardConfig(enforcement_mode="bad_mode")


class TestLogMode:
    """Tests for log enforcement mode."""

    async def test_log_mode_passes_response_on_blocking(self) -> None:
        """Test that log mode passes through response even when blocking occurs."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)  # Block the event loop
            await asyncio.sleep(0.02)  # Give monitor time to detect
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="log",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Warmup request to start monitor
            await client.get("/blocking")
            await asyncio.sleep(0.1)

            # Actual test request
            response = await client.get("/blocking")

        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}
        # No blocking headers in log mode without dev_mode
        assert "x-blocking-count" not in response.headers

    async def test_log_mode_with_dev_mode_adds_headers(self) -> None:
        """Test that log mode with dev_mode=True adds headers but doesn't block."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="log",
            dev_mode=True,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        # Response passes through
        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}
        # Headers are added in dev_mode
        assert "x-request-id" in response.headers


class TestWarnMode:
    """Tests for warn enforcement mode."""

    async def test_warn_mode_passes_response_on_blocking(self) -> None:
        """Test that warn mode passes through response when blocking occurs."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="warn",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        # Response still passes through
        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}

    async def test_warn_mode_adds_warning_header(self) -> None:
        """Test that warn mode adds warning header when blocking detected."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="warn",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        assert response.headers.get("x-loopguard-warning") == "blocking-detected"
        assert response.headers.get("x-blocking-detected") == "true"

    async def test_warn_mode_no_warning_header_when_no_blocking(self) -> None:
        """Test that warn mode doesn't add warning header when no blocking."""
        app = FastAPI()

        @app.get("/fast")
        async def fast_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.001)
            return {"status": "fast"}

        config = LoopGuardConfig(
            enforcement_mode="warn",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/fast")

        assert response.status_code == 200
        assert "x-loopguard-warning" not in response.headers
        assert response.headers.get("x-blocking-detected") == "false"


class TestStrictMode:
    """Tests for strict enforcement mode."""

    async def test_strict_mode_returns_503_on_blocking(self) -> None:
        """Test that strict mode returns 503 when blocking is detected."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        assert response.status_code == 503

    async def test_strict_mode_returns_json_for_api_clients(self) -> None:
        """Test that strict mode returns JSON for Accept: application/json."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking", headers={"Accept": "application/json"})
            await asyncio.sleep(0.1)
            response = await client.get(
                "/blocking",
                headers={"Accept": "application/json"},
            )

        assert response.status_code == 503
        assert "application/json" in response.headers["content-type"]
        data = response.json()
        assert data["error"] == "event_loop_blocked"
        assert "help" in data
        assert "common_causes" in data["help"]

    async def test_strict_mode_returns_html_for_browsers(self) -> None:
        """Test that strict mode returns HTML for Accept: text/html."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking", headers={"Accept": "text/html"})
            await asyncio.sleep(0.1)
            response = await client.get(
                "/blocking",
                headers={"Accept": "text/html"},
            )

        assert response.status_code == 503
        assert "text/html" in response.headers["content-type"]
        assert "Event Loop Blocked" in response.text
        assert "asyncio.sleep" in response.text

    async def test_strict_mode_passes_non_blocking_requests(self) -> None:
        """Test that strict mode passes through non-blocking requests."""
        app = FastAPI()

        @app.get("/fast")
        async def fast_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.001)
            return {"status": "fast"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/fast")

        assert response.status_code == 200
        assert response.json() == {"status": "fast"}

    async def test_strict_mode_includes_enforcement_header(self) -> None:
        """Test that strict mode includes x-loopguard-enforcement header."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            dev_mode=False,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        assert response.headers.get("x-loopguard-enforcement") == "strict"


class TestDevModeEscalation:
    """Tests for dev_mode auto-escalation to strict mode."""

    async def test_dev_mode_escalates_warn_to_strict(self) -> None:
        """Test that dev_mode=True escalates warn mode to strict."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="warn",  # Would normally be warn
            dev_mode=True,  # But dev_mode escalates to strict
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        # Should get 503 because dev_mode escalates to strict
        assert response.status_code == 503

    async def test_dev_mode_respects_explicit_log_mode(self) -> None:
        """Test that dev_mode=True respects explicit log mode (no escalation)."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enforcement_mode="log",  # Explicitly log
            dev_mode=True,  # dev_mode won't escalate log to strict
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        # Should pass through because explicit log mode is respected
        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}
        # But should still have dev headers
        assert "x-request-id" in response.headers

    async def test_dev_mode_escalates_default_to_strict(self) -> None:
        """Test that dev_mode=True escalates default (warn) to strict."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        # Don't specify enforcement_mode - use default (warn)
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/blocking")
            await asyncio.sleep(0.1)
            response = await client.get("/blocking")

        # Should get 503 because dev_mode escalates default (warn) to strict
        assert response.status_code == 503


class TestEffectiveEnforcementMode:
    """Tests for _get_effective_enforcement_mode method."""

    def test_effective_mode_without_dev_mode(self) -> None:
        """Test effective mode returns configured mode when dev_mode=False."""
        app = FastAPI()

        for mode in ["log", "warn", "strict"]:
            config = LoopGuardConfig(
                enforcement_mode=mode,
                dev_mode=False,
            )
            middleware = LoopGuardMiddleware(app, config=config)
            assert middleware._get_effective_enforcement_mode() == mode

    def test_effective_mode_with_dev_mode_escalates(self) -> None:
        """Test effective mode escalates to strict when dev_mode=True."""
        app = FastAPI()

        # warn -> strict
        config = LoopGuardConfig(enforcement_mode="warn", dev_mode=True)
        middleware = LoopGuardMiddleware(app, config=config)
        assert middleware._get_effective_enforcement_mode() == "strict"

        # strict -> strict (no change)
        config = LoopGuardConfig(enforcement_mode="strict", dev_mode=True)
        middleware = LoopGuardMiddleware(app, config=config)
        assert middleware._get_effective_enforcement_mode() == "strict"

    def test_effective_mode_log_not_escalated(self) -> None:
        """Test that log mode is not escalated even with dev_mode=True."""
        app = FastAPI()

        config = LoopGuardConfig(enforcement_mode="log", dev_mode=True)
        middleware = LoopGuardMiddleware(app, config=config)
        assert middleware._get_effective_enforcement_mode() == "log"
