#!/usr/bin/env python3
"""CLI runner for LoopGuard stress tests with metrics collection.

This script orchestrates stress testing by:
1. Optionally running Locust load tests
2. Running a validation suite to verify middleware behavior
3. Collecting and reporting metrics

Usage:
    # Full stress test (requires stress_app.py running on port 8000):
    python examples/run_stress_test.py --users 500 --duration 60

    # Validation suite only (skip Locust):
    python examples/run_stress_test.py --skip-locust

    # Custom host:
    python examples/run_stress_test.py --host http://localhost:9000
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class StressTestResults:
    """Aggregated stress test results."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    unique_request_ids: set[str] = field(default_factory=set)
    blocking_detected_count: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    total_blocking_ms: float = 0.0
    endpoint_stats: dict[str, dict[str, Any]] = field(
        default_factory=lambda: defaultdict(
            lambda: {"count": 0, "blocking_detected": 0, "total_blocking_ms": 0.0}
        )
    )
    registry_leaks: int = 0
    missing_headers: list[str] = field(default_factory=list)


async def run_validation_suite(base_url: str) -> StressTestResults:
    """Run validation suite to verify LoopGuard behavior.

    This suite tests:
    1. Unique request IDs under concurrency
    2. Registry cleanup after requests complete
    3. Blocking detection accuracy
    4. Response header completeness
    5. Excluded path behavior

    Args:
        base_url: The base URL of the stress test server.

    Returns:
        StressTestResults with all collected metrics.
    """
    results = StressTestResults()

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        print("\n📊 Running validation suite...")

        # Test 1: Unique request IDs under concurrency
        print("  [1/5] Testing unique request IDs (100 concurrent)...")
        tasks = [client.get("/") for _ in range(100)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for r in responses:
            if isinstance(r, Exception):
                results.failed_requests += 1
                continue
            results.successful_requests += 1
            if "x-request-id" in r.headers:
                results.unique_request_ids.add(r.headers["x-request-id"])

        unique_count = len(results.unique_request_ids)
        status = "✓" if unique_count == 100 else "✗"
        print(f"      {status} {unique_count}/100 unique IDs")

        # Test 2: Registry cleanup
        print("  [2/5] Checking registry cleanup...")
        await asyncio.sleep(0.5)  # Wait for cleanup
        r = await client.get("/debug/registry")
        data = r.json()
        # Note: active_count of 1 is expected (the current /debug/registry request)
        # So we check for <= 1, and report leaks as count - 1
        active = data["active_count"]
        results.registry_leaks = max(0, active - 1)  # Exclude current request
        status = "✓" if active <= 1 else "✗"
        print(f"      {status} Active contexts: {active} (expected: 1 for self)")

        # Test 3: Blocking detection accuracy
        print("  [3/5] Testing blocking detection...")
        blocking_endpoints = [
            ("/blocking/short", True),
            ("/blocking/medium", True),
            ("/blocking/long", True),
            ("/async/short", False),
            ("/async/medium", False),
        ]

        for endpoint, should_block in blocking_endpoints:
            r = await client.get(endpoint)
            detected = r.headers.get("x-blocking-detected") == "true"
            count = int(r.headers.get("x-blocking-count", "0"))

            if should_block and not detected:
                results.false_negatives += 1
                print(f"      ✗ {endpoint}: expected blocking, got none")
            elif not should_block and detected:
                results.false_positives += 1
                print(f"      ✗ {endpoint}: false positive (count={count})")
            else:
                status = "blocked" if detected else "clean"
                print(f"      ✓ {endpoint}: {status} as expected")

        # Test 4: Header completeness
        print("  [4/5] Validating response headers...")
        r = await client.get("/blocking/medium")
        required_headers = [
            "x-request-id",
            "x-blocking-count",
            "x-blocking-total-ms",
            "x-blocking-detected",
        ]
        missing = [h for h in required_headers if h not in r.headers]
        results.missing_headers = missing

        if missing:
            print(f"      ✗ Missing headers: {missing}")
        else:
            print("      ✓ All headers present")
            print(f"        - x-request-id: {r.headers['x-request-id']}")
            print(f"        - x-blocking-count: {r.headers['x-blocking-count']}")
            print(f"        - x-blocking-total-ms: {r.headers['x-blocking-total-ms']}")
            print(f"        - x-blocking-detected: {r.headers['x-blocking-detected']}")

        # Test 5: Excluded paths
        print("  [5/5] Testing excluded paths...")
        r = await client.get("/health")
        has_loopguard = "x-request-id" in r.headers
        status = "✗" if has_loopguard else "✓"
        excluded_status = "no" if has_loopguard else "yes"
        print(f"      {status} /health excluded: {excluded_status}")

    return results


async def run_high_concurrency_test(
    base_url: str, concurrency: int = 500
) -> StressTestResults:
    """Run high concurrency test.

    Args:
        base_url: The base URL of the stress test server.
        concurrency: Number of concurrent requests.

    Returns:
        StressTestResults with concurrency test metrics.
    """
    results = StressTestResults()

    print(f"\n🔥 Running high concurrency test ({concurrency} concurrent)...")

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        # Warm up
        await client.get("/")
        await asyncio.sleep(0.1)

        # Concurrent requests
        tasks = [client.get("/") for _ in range(concurrency)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for r in responses:
            results.total_requests += 1
            if isinstance(r, Exception):
                results.failed_requests += 1
                continue
            results.successful_requests += 1
            if "x-request-id" in r.headers:
                results.unique_request_ids.add(r.headers["x-request-id"])

        # Check registry
        await asyncio.sleep(0.5)
        r = await client.get("/debug/registry")
        data = r.json()
        # active_count of 1 is expected (the current request)
        active = data["active_count"]
        results.registry_leaks = max(0, active - 1)

    unique = len(results.unique_request_ids)
    print(f"      Successful: {results.successful_requests}/{concurrency}")
    print(f"      Unique IDs: {unique}/{concurrency}")
    print(f"      Registry leaks: {results.registry_leaks} (active: {active})")

    return results


def print_summary(results: StressTestResults) -> None:
    """Print test summary."""
    print("\n" + "=" * 60)
    print("📈 STRESS TEST SUMMARY")
    print("=" * 60)

    print("\n🔢 Request Statistics:")
    print(f"   Total successful: {results.successful_requests}")
    print(f"   Total failed: {results.failed_requests}")
    print(f"   Unique request IDs: {len(results.unique_request_ids)}")

    print("\n🎯 Detection Accuracy:")
    print(f"   False positives: {results.false_positives}")
    print(f"   False negatives: {results.false_negatives}")

    print("\n🧹 Resource Management:")
    print(f"   Registry leaks: {results.registry_leaks}")

    if results.missing_headers:
        print("\n⚠️  Missing Headers:")
        for header in results.missing_headers:
            print(f"   - {header}")

    # Overall verdict
    print("\n" + "=" * 60)
    all_passed = (
        results.failed_requests == 0
        and results.false_positives == 0
        and results.registry_leaks == 0
        and len(results.missing_headers) == 0
    )
    if all_passed:
        print("✅ ALL STRESS TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
        if results.failed_requests > 0:
            print(f"   - {results.failed_requests} requests failed")
        if results.false_positives > 0:
            print(f"   - {results.false_positives} false positives")
        if results.registry_leaks > 0:
            print(f"   - {results.registry_leaks} registry leaks")
        if results.missing_headers:
            print(f"   - Missing headers: {results.missing_headers}")
    print("=" * 60)


def run_locust(
    host: str,
    users: int,
    spawn_rate: int,
    duration: int,
) -> bool:
    """Run Locust load test.

    Args:
        host: Target host URL.
        users: Number of concurrent users.
        spawn_rate: Users spawned per second.
        duration: Test duration in seconds.

    Returns:
        True if Locust ran successfully, False otherwise.
    """
    print("\n📍 Starting Locust load test...")
    print(f"   Users: {users}")
    print(f"   Spawn rate: {spawn_rate}/s")
    print(f"   Duration: {duration}s")

    locust_cmd = [
        "locust",
        "-f",
        "examples/locustfile.py",
        "--host",
        host,
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        f"{duration}s",
        "--csv",
        "stress_results",
    ]

    try:
        subprocess.run(locust_cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Locust failed: {e}")
        return False
    except FileNotFoundError:
        print("❌ Locust not installed. Run: pip install locust")
        return False


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LoopGuard Stress Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run full stress test:
    python examples/run_stress_test.py --users 500 --duration 60

    # Run validation only:
    python examples/run_stress_test.py --skip-locust

    # Run with custom concurrency test:
    python examples/run_stress_test.py --skip-locust --concurrency 1000
        """,
    )
    parser.add_argument(
        "--users",
        "-u",
        type=int,
        default=500,
        help="Number of concurrent users (default: 500)",
    )
    parser.add_argument(
        "--duration",
        "-t",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--spawn-rate",
        "-r",
        type=int,
        default=50,
        help="Users spawned per second (default: 50)",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:8000",
        help="Target host (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--skip-locust",
        action="store_true",
        help="Skip Locust, run validation only",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=500,
        help="Concurrency level for validation test (default: 500)",
    )
    args = parser.parse_args()

    print("🚀 LoopGuard Stress Test")
    print(f"   Target: {args.host}")

    # Run Locust if not skipped
    if not args.skip_locust:
        success = run_locust(
            host=args.host,
            users=args.users,
            spawn_rate=args.spawn_rate,
            duration=args.duration,
        )
        if not success:
            print("\n⚠️  Continuing with validation suite...")

    # Run validation suite
    results = asyncio.run(run_validation_suite(args.host))

    # Run high concurrency test
    concurrency_results = asyncio.run(
        run_high_concurrency_test(args.host, args.concurrency)
    )

    # Merge results
    results.total_requests += concurrency_results.total_requests
    results.successful_requests += concurrency_results.successful_requests
    results.failed_requests += concurrency_results.failed_requests
    results.unique_request_ids.update(concurrency_results.unique_request_ids)
    results.registry_leaks = max(
        results.registry_leaks, concurrency_results.registry_leaks
    )

    # Print summary
    print_summary(results)

    # Exit with appropriate code
    all_passed = (
        results.failed_requests == 0
        and results.false_positives == 0
        and results.registry_leaks == 0
    )
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
