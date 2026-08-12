"""Tests for enforcement mode feature."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware
from fastapi_loopguard.context import get_active_requests, get_registry

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.types import Message, Receive, Scope, Send


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


class TestDevModeDoesNotEscalate:
    """dev_mode only controls headers; it must never change the response status."""

    async def test_dev_mode_default_mode_returns_200_on_blocking(self) -> None:
        """dev_mode with the default (warn) mode passes the response through."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        config = LoopGuardConfig(
            dev_mode=True,  # Must not escalate the default (warn) to strict
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

        # Response passes through with warn-mode diagnostics, no 503
        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}
        assert response.headers.get("x-blocking-detected") == "true"
        assert response.headers.get("x-loopguard-warning") == "blocking-detected"

    async def test_innocent_concurrent_requests_not_failed(self) -> None:
        """Requests in flight during another request's blocking must not 503.

        Blocking is attributed to ALL in-flight requests (the sentinel cannot
        know the culprit), so a 503 on blocking_count > 0 punishes bystanders.
        Only explicit strict mode may fail responses.
        """
        app = FastAPI()

        @app.get("/block")
        async def block_endpoint() -> dict[str, str]:
            time.sleep(0.1)  # Sync block; returns without yielding after
            return {"status": "blocked"}

        @app.get("/fast")
        async def fast_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.2)  # In flight while /block freezes the loop
            return {"status": "fast"}

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

            async def blocker() -> int:
                await asyncio.sleep(0.05)  # Let the fast requests register
                return (await client.get("/block")).status_code

            async def fast() -> int:
                return (await client.get("/fast")).status_code

            statuses = await asyncio.gather(*(fast() for _ in range(5)), blocker())

        # Nobody gets a 503 outside explicit strict mode
        assert statuses == [200] * 6

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


class TestEffectiveEnforcementMode:
    """Tests for _get_effective_enforcement_mode method."""

    def test_effective_mode_is_configured_mode(self) -> None:
        """Effective mode is always the configured mode, regardless of dev_mode."""
        app = FastAPI()

        for mode in ["log", "warn", "strict"]:
            for dev_mode in [False, True]:
                config = LoopGuardConfig(
                    enforcement_mode=mode,
                    dev_mode=dev_mode,
                )
                middleware = LoopGuardMiddleware(app, config=config)
                assert middleware._get_effective_enforcement_mode() == mode


class TestStrictModeStreaming:
    """Strict mode and responses whose headers are already on the wire."""

    async def test_mid_stream_blocking_is_not_enforced(self) -> None:
        """Blocking first observed mid-stream cannot fail the response.

        Headers went out with the first chunk; the 200 and the
        x-blocking-detected: false header reflect the state at that moment.
        Documents the streaming limitation recorded in FINDINGS.md — the
        stall is reported via logs only.
        """
        config = LoopGuardConfig(enforcement_mode="strict", log_blocking_events=False)
        sent: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {"type": "http.response.body", "body": b"chunk1", "more_body": True}
            )
            # A stall observed while the body streams
            ctx = next(iter(get_active_requests()))
            ctx.record_blocking(100.0)
            await send(
                {"type": "http.response.body", "body": b"chunk2", "more_body": False}
            )

        middleware = LoopGuardMiddleware(app, config=config)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/stream",
            "headers": [],
        }
        await middleware(scope, receive, send)

        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 200
        headers = dict(sent[0]["headers"])
        assert headers[b"x-blocking-detected"] == b"false"
        bodies = [m for m in sent if m["type"] == "http.response.body"]
        assert len(bodies) == 2  # both chunks forwarded; no 503 replaced them

    async def test_app_exception_after_swallowed_start_loses_503(self) -> None:
        """Documents accepted behavior (FINDINGS.md): the exception wins.

        When strict mode has swallowed the app's response start and the app
        then raises, the exception propagates: the client gets the server's
        500, not LoopGuard's 503, and nothing is sent from here.
        """
        config = LoopGuardConfig(enforcement_mode="strict", log_blocking_events=False)
        sent: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            ctx = next(iter(get_active_requests()))
            ctx.record_blocking(100.0)
            # Swallowed by strict mode (blocking already recorded)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("handler exploded")

        middleware = LoopGuardMiddleware(app, config=config)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {"type": "http", "method": "GET", "path": "/boom", "headers": []}
        with pytest.raises(RuntimeError, match="handler exploded"):
            await middleware(scope, receive, send)

        assert sent == []  # neither the app's 200 nor a LoopGuard 503


class TestStrictModeHeaders:
    """Full header contract of the strict 503 and the clean pass-through."""

    def _blocking_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        @app.get("/fast")
        async def fast_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.001)
            return {"status": "fast"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)
        return app

    async def test_503_carries_full_strict_header_set(self) -> None:
        app = self._blocking_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/fast")
            await asyncio.sleep(0.05)
            response = await client.get("/blocking")

        assert response.status_code == 503
        assert response.headers.get("x-loopguard-enforcement") == "strict"
        assert "x-request-id" in response.headers
        assert int(response.headers["x-blocking-count"]) >= 1
        assert float(response.headers["x-blocking-total-ms"]) > 0
        # The strict 503 header set omits x-blocking-detected by contract
        assert "x-blocking-detected" not in response.headers
        assert int(response.headers["content-length"]) == len(response.content)

    async def test_clean_strict_response_carries_diagnostic_headers(self) -> None:
        app = self._blocking_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/fast")

        assert response.status_code == 200
        assert response.headers.get("x-blocking-detected") == "false"
        assert response.headers.get("x-blocking-count") == "0"
        assert "x-loopguard-enforcement" not in response.headers

    async def test_missing_accept_header_gets_json(self) -> None:
        app = self._blocking_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/fast")
            await asyncio.sleep(0.05)
            response = await client.get("/blocking", headers={"Accept": ""})

        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/json")


class TestStrictModeBystanders:
    """Documents FINDINGS: strict mode 503s every in-flight request.

    The sentinel measures lag, not call stacks, so it cannot name the
    culprit; under concurrency, strict mode punishes bystanders. This is
    the documented reason strict is opt-in (invariant 6).
    """

    async def test_concurrent_bystander_also_gets_503(self) -> None:
        app = FastAPI()

        @app.get("/blocking")
        async def blocking_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.02)  # let the bystander register first
            time.sleep(0.1)
            await asyncio.sleep(0.02)
            return {"status": "blocked"}

        @app.get("/innocent")
        async def innocent_endpoint() -> dict[str, str]:
            await asyncio.sleep(0.2)  # in flight during the stall
            return {"status": "innocent"}

        config = LoopGuardConfig(
            enforcement_mode="strict",
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/innocent")  # warmup: start monitor
            await asyncio.sleep(0.05)

            culprit, bystander = await asyncio.gather(
                client.get("/blocking"),
                client.get("/innocent"),
            )

        assert culprit.status_code == 503
        # The bystander was in flight during the stall, so it is 503'd too
        assert bystander.status_code == 503
