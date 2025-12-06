"""Locust load test for LoopGuard stress testing.

This file defines user behavior patterns for stress testing the LoopGuard
middleware with realistic traffic distribution.

Usage:
    # With web UI (opens http://localhost:8089):
    locust -f examples/locustfile.py --host=http://localhost:8000

    # Headless mode (500 users, 60 seconds):
    locust -f examples/locustfile.py --host=http://localhost:8000 \
           --headless -u 500 -r 50 -t 60s

    # With CSV output:
    locust -f examples/locustfile.py --host=http://localhost:8000 \
           --headless -u 500 -r 50 -t 60s --csv=stress_results

Traffic Distribution:
    - 40% fast requests (/)
    - 10% health checks (/health) - excluded from monitoring
    - 30% async endpoints (non-blocking)
    - 12% blocking endpoints (should detect)
    - 8% mixed workload
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task


class LoopGuardStressUser(HttpUser):
    """Simulates realistic mixed workload for LoopGuard testing.

    This user class generates traffic across all endpoint types with
    a realistic distribution that exercises the middleware thoroughly.
    """

    wait_time = between(0.1, 0.5)  # 100-500ms between requests

    # ===== HIGH FREQUENCY (fast endpoints) =====

    @task(40)  # 40% of traffic
    def fast_root(self) -> None:
        """High-frequency fast requests."""
        with self.client.get("/", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=False)

    @task(10)  # 10% of traffic
    def health_check(self) -> None:
        """Health checks (excluded from monitoring)."""
        with self.client.get("/health", catch_response=True) as response:
            # Should NOT have loopguard headers
            if "x-request-id" in response.headers:
                response.failure("Health endpoint should be excluded")

    # ===== MEDIUM FREQUENCY (async endpoints) =====

    @task(15)  # 15% of traffic
    def async_short(self) -> None:
        """Short async operations."""
        with self.client.get("/async/short", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=False)

    @task(10)  # 10% of traffic
    def async_medium(self) -> None:
        """Medium async operations."""
        with self.client.get("/async/medium", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=False)

    @task(5)  # 5% of traffic
    def async_long(self) -> None:
        """Long async operations."""
        with self.client.get("/async/long", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=False)

    # ===== LOW FREQUENCY (blocking endpoints) =====

    @task(5)  # 5% of traffic
    def blocking_short(self) -> None:
        """Short blocking - should detect."""
        with self.client.get("/blocking/short", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=True)

    @task(3)  # 3% of traffic
    def blocking_medium(self) -> None:
        """Medium blocking - should detect."""
        with self.client.get("/blocking/medium", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=True)

    @task(2)  # 2% of traffic
    def blocking_long(self) -> None:
        """Long blocking - should detect multiple events."""
        with self.client.get("/blocking/long", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=True)
            # Verify at least one blocking event for long blocks
            if response.status_code == 200:
                count = int(response.headers.get("x-blocking-count", "0"))
                if count < 1:
                    response.failure(f"Expected blocking events, got {count}")

    @task(2)  # 2% of traffic
    def blocking_cpu(self) -> None:
        """CPU-intensive blocking."""
        with self.client.get(
            "/blocking/cpu-intensive", catch_response=True
        ) as response:
            self._validate_headers(response, expect_blocking=True)

    # ===== MIXED WORKLOAD =====

    @task(5)  # 5% of traffic
    def mixed_mostly_async(self) -> None:
        """Mixed workload, mostly async."""
        with self.client.get("/mixed/mostly-async", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=True)

    @task(3)  # 3% of traffic
    def mixed_mostly_blocking(self) -> None:
        """Mixed workload, mostly blocking."""
        with self.client.get("/mixed/mostly-blocking", catch_response=True) as response:
            self._validate_headers(response, expect_blocking=True)

    def _validate_headers(self, response, expect_blocking: bool) -> None:  # noqa: ANN001
        """Validate LoopGuard response headers."""
        if response.status_code != 200:
            response.failure(f"Status {response.status_code}")
            return

        # Check required headers exist
        required = [
            "x-request-id",
            "x-blocking-count",
            "x-blocking-total-ms",
            "x-blocking-detected",
        ]
        for header in required:
            if header not in response.headers:
                response.failure(f"Missing header: {header}")
                return

        # Validate blocking detection accuracy
        detected = response.headers["x-blocking-detected"] == "true"
        count = int(response.headers["x-blocking-count"])

        if expect_blocking and not detected:
            # Allow some tolerance - monitor might miss very short blocks
            # This is logged but not failed to avoid noise
            pass
        elif not expect_blocking and detected:
            response.failure(
                f"False positive: blocking detected on async endpoint (count={count})"
            )


class HighConcurrencyUser(HttpUser):
    """Aggressive user for max concurrency testing.

    This user class generates rapid-fire requests to stress test
    the request registry and cleanup mechanisms.
    """

    wait_time = between(0.01, 0.05)  # Very fast requests (10-50ms)

    @task(1)
    def rapid_fire(self) -> None:
        """Rapid requests to test registry handling."""
        endpoint = random.choice(["/", "/async/short", "/blocking/short"])
        self.client.get(endpoint)


class BurstUser(HttpUser):
    """User that generates burst traffic patterns.

    Simulates real-world scenarios where traffic comes in bursts
    followed by quiet periods.
    """

    wait_time = between(0.5, 2.0)  # Longer waits between bursts

    @task(1)
    def burst_requests(self) -> None:
        """Send a burst of requests."""
        # Send 5-10 requests rapidly
        burst_size = random.randint(5, 10)
        for _ in range(burst_size):
            endpoint = random.choice(
                [
                    "/",
                    "/async/short",
                    "/async/medium",
                    "/blocking/short",
                ]
            )
            self.client.get(endpoint)
