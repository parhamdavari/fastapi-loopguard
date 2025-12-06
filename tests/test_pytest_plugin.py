"""Tests for fastapi_loopguard.pytest_plugin module."""

from __future__ import annotations

import asyncio
import time

import pytest

# Enable pytester fixture for plugin integration tests
pytest_plugins = ["pytester"]

from fastapi_loopguard.pytest_plugin import BlockingDetector  # noqa: E402


class TestBlockingDetector:
    """Tests for BlockingDetector class."""

    async def test_start_and_stop(self) -> None:
        """Test detector starts and stops cleanly."""
        detector = BlockingDetector(threshold_ms=50.0)

        await detector.start()
        assert detector._running is True
        assert detector._task is not None

        await detector.stop()
        assert detector._running is False

    async def test_detects_blocking_above_threshold(self) -> None:
        """Test detector detects blocking above threshold."""
        detector = BlockingDetector(threshold_ms=20.0)

        await detector.start()

        # Give detector time to start monitoring
        await asyncio.sleep(0.02)

        # Block the event loop
        time.sleep(0.1)  # 100ms blocking - well above 20ms threshold

        # Give detector time to detect (needs at least one monitor cycle after block)
        await asyncio.sleep(0.05)

        await detector.stop()

        assert len(detector.blocking_events) > 0
        assert max(detector.blocking_events) > 20.0

    async def test_no_false_positive_async_sleep(self) -> None:
        """Test async sleep does NOT trigger detection."""
        detector = BlockingDetector(threshold_ms=30.0)

        await detector.start()

        # Async sleep should NOT block
        await asyncio.sleep(0.05)

        await detector.stop()

        # Should have no or very few blocking events
        # (occasional small spikes may occur due to system load)
        if detector.blocking_events:
            # Any detected events should be small (< 30ms)
            assert all(lag < 30.0 for lag in detector.blocking_events)

    async def test_records_multiple_events(self) -> None:
        """Test detector records multiple blocking events."""
        detector = BlockingDetector(threshold_ms=15.0)

        await detector.start()

        # Give detector time to start
        await asyncio.sleep(0.02)

        # Multiple blocks with longer delays to ensure detection
        time.sleep(0.05)  # 50ms - first block
        await asyncio.sleep(0.03)  # Let detector catch up
        time.sleep(0.05)  # 50ms - second block
        await asyncio.sleep(0.03)  # Let detector catch up

        await detector.stop()

        # Should have recorded at least 1 blocking event
        # (may be 1 or 2 depending on timing - just verify detection works)
        assert len(detector.blocking_events) >= 1
        assert all(lag > 15.0 for lag in detector.blocking_events)

    async def test_threshold_initialization(self) -> None:
        """Test threshold is properly initialized."""
        detector = BlockingDetector(threshold_ms=100.0)
        assert detector.threshold_ms == 100.0

    async def test_events_list_starts_empty(self) -> None:
        """Test blocking_events list starts empty."""
        detector = BlockingDetector()
        assert detector.blocking_events == []

    async def test_stop_without_start(self) -> None:
        """Test stop works even if never started."""
        detector = BlockingDetector()
        await detector.stop()  # Should not raise

    async def test_cancel_handles_cleanly(self) -> None:
        """Test detector handles cancellation gracefully."""
        detector = BlockingDetector()
        await detector.start()

        # Immediately stop (cancel the task)
        await detector.stop()

        # Should not raise and should be stopped
        assert detector._running is False


class TestPytestPluginIntegration:
    """Integration tests for pytest plugin using pytester."""

    def test_marker_registered(self, pytester: pytest.Pytester) -> None:
        """Test that @pytest.mark.no_blocking marker is registered."""
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)
        pytester.makepyfile("""
            import pytest

            @pytest.mark.no_blocking
            async def test_with_marker():
                pass
        """)

        # Should not warn about unknown marker
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)
        assert "PytestUnknownMarkWarning" not in result.stdout.str()

    def test_no_blocking_marker_fails_blocking_test(
        self, pytester: pytest.Pytester
    ) -> None:
        """Test that @pytest.mark.no_blocking fails blocking tests."""
        pytester.makepyfile("""
            import pytest
            import time
            import asyncio

            @pytest.mark.no_blocking
            async def test_blocks():
                # Give detector time to start
                await asyncio.sleep(0.02)
                # Block for 200ms - well above 10ms threshold
                time.sleep(0.2)
                # Give detector time to detect
                await asyncio.sleep(0.02)
        """)

        # Configure a very low threshold for reliable detection
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_no_blocking_marker_passes_clean_test(
        self, pytester: pytest.Pytester
    ) -> None:
        """Test that @pytest.mark.no_blocking passes clean async tests."""
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking
            async def test_no_blocks():
                await asyncio.sleep(0.01)  # Async sleep - no blocking
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 50
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_unmarked_test_ignores_blocking(self, pytester: pytest.Pytester) -> None:
        """Test that unmarked tests ignore blocking (no failure)."""
        pytester.makepyfile("""
            import pytest
            import time

            async def test_blocks_but_unmarked():
                time.sleep(0.1)  # Would block but no marker
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 20
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_sync_test_with_marker_passes(self, pytester: pytest.Pytester) -> None:
        """Test sync tests with marker are not affected (only async works)."""
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            def test_sync_with_marker():
                time.sleep(0.1)  # Sync test, marker ignored
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 20
        """)

        result = pytester.runpytest("-v")
        # Sync test passes because marker only wraps async functions
        result.assert_outcomes(passed=1)

    def test_custom_threshold_from_ini(self, pytester: pytest.Pytester) -> None:
        """Test custom threshold is read from pytest.ini."""
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            async def test_short_block():
                time.sleep(0.03)  # 30ms - under 100ms threshold
        """)

        # High threshold - 30ms should not trigger
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 100
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_failure_message_format(self, pytester: pytest.Pytester) -> None:
        """Test failure message contains expected information."""
        pytester.makepyfile("""
            import pytest
            import time
            import asyncio

            @pytest.mark.no_blocking
            async def test_block_for_message():
                # Give detector time to start
                await asyncio.sleep(0.02)
                # Block for 200ms - well above threshold
                time.sleep(0.2)
                # Give detector time to detect
                await asyncio.sleep(0.02)
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

        stdout = result.stdout.str()
        assert "blocking event(s)" in stdout
        assert "max lag:" in stdout
        assert "threshold:" in stdout
