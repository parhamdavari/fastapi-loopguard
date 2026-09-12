"""Tests for scoping blocking measurement to a window inside a test (#85).

`loopguard_pause()` and `loopguard_only()` are two synchronous context
managers in `fastapi_loopguard.pytest_plugin`. Neither awaits, and the
import path stays the plugin module -- CLAUDE.md is explicit that it is not
re-exported from `__init__.py`, and the issue rules out a
`fastapi_loopguard.testing` alias.

The straddling tick is the part that is easy to get wrong, so most of these
tests are about the two edges rather than the middle: entering must bank the
pre-entry portion of the in-flight tick (blocking *before* the window is
still charged), and leaving must neutralise the tick that spans the exit
(the setup stall must not be recorded by the tick that resumes after it).
That is invariant 9's "no millisecond counted twice, none dropped" applied
to a user-defined window.

Written against a source that does not implement any of this yet, so most
of these fail today; the ones that document already-correct behaviour say
so in their docstrings.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

# Enable pytester fixture for plugin integration tests
pytest_plugins = ["pytester"]

from fastapi_loopguard import pytest_plugin  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]

# 10ms is the threshold the issue's acceptance criteria name, against a
# 200ms block inside the window: a 20x gap, so the block cannot be missed.
# Every test using it keeps the *measured* region down to a short await
# doing nothing, since a tight threshold is only free for tests asserting
# that blocking IS detected (CLAUDE.md).
_TIGHT_INI = """
    [pytest]
    asyncio_mode = auto
    loopguard_threshold_ms = 10
"""

_TIGHT_ALL_ASYNC_INI = """
    [pytest]
    asyncio_mode = auto
    loopguard_threshold_ms = 10
    loopguard_all_async = true
"""


def _report(pytester: pytest.Pytester) -> dict[str, Any]:
    report_file = pytester.path / "loopguard.json"
    assert report_file.exists()
    parsed: dict[str, Any] = json.loads(report_file.read_text())
    return parsed


def _max_lag_ms(report: dict[str, Any]) -> float:
    lags = [event["lag_ms"] for record in report["tests"] for event in record["events"]]
    assert lags, "report contains no blocking events"
    return max(lags)


class TestScopedMeasurementApi:
    """The public surface: two managers, one import path, no alias."""

    def test_documented_import_path_and_no_testing_alias(self) -> None:
        """Both managers import from `fastapi_loopguard.pytest_plugin`.

        Imported inside the test rather than at module scope so that a
        source without them fails this one test instead of erroring the
        whole file at collection.
        """
        import importlib.util

        import fastapi_loopguard
        from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

        assert callable(loopguard_pause)
        assert callable(loopguard_only)

        # The issue rules both of these out: no parallel `testing` module,
        # and the plugin stays absent from the package's own namespace.
        assert importlib.util.find_spec("fastapi_loopguard.testing") is None
        assert not hasattr(fastapi_loopguard, "loopguard_pause")
        assert not hasattr(fastapi_loopguard, "loopguard_only")

    def test_pytest_plugin_still_imports_nothing_from_monitor(self) -> None:
        """Characterization test: already true today, and must stay true.

        The window machinery needs a poll and a watermark, which
        `monitor.py` also has. Sharing them would put the middleware's
        import graph on the plugin's path; the issue requires the plugin
        keep its own copy. Read off the AST so a comment cannot fool it.
        """
        source = Path(pytest_plugin.__file__).read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert not [name for name in imported if name.split(".")[-1] == "monitor"]


class TestLoopguardPause:
    """`loopguard_pause()`: stop measuring for the duration of the block."""

    def test_block_inside_pause_is_not_charged(self, pytester: pytest.Pytester) -> None:
        """The 55-test case from the field report.

        A 200ms block inside the window, under a 10ms threshold, passes.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_setup_is_scoped_out():
                await asyncio.sleep(0.02)
                with loopguard_pause():
                    time.sleep(0.2)
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_block_inside_pause_without_trailing_await(
        self, pytester: pytest.Pytester
    ) -> None:
        """The case a naive implementation fails.

        With no await after the window, the monitor's pending sleep expired
        during the block and is measured by `stop()`'s own poll. Suppressing
        only what is recorded *while* paused would leave that straddling
        tick carrying the whole 200ms stall, so the exit has to leave a
        watermark the later measurement is taken against.
        """
        pytester.makepyfile("""
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_setup_then_return():
                # No await anywhere after the block: the monitor never gets
                # a turn of its own before the test returns.
                with loopguard_pause():
                    time.sleep(0.2)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_block_outside_pause_still_flags(self, pytester: pytest.Pytester) -> None:
        """Scoping setup out must not blind the rest of the test."""
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_blocks_after_the_window():
                with loopguard_pause():
                    time.sleep(0.05)
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_block_before_pause_is_still_charged(
        self, pytester: pytest.Pytester
    ) -> None:
        """Entering banks the pre-entry portion of the in-flight tick.

        The 200ms block here is followed by no await at all, so the only
        thing that can ever measure it is the poll on entering the window.
        An implementation that just flips a suppression flag swallows it,
        and a real stall vanishes because the author happened to scope the
        next few lines.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_blocks_before_the_window():
                await asyncio.sleep(0.02)
                time.sleep(0.2)  # never awaited after: only the enter-poll sees it
                with loopguard_pause():
                    time.sleep(0.05)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

        # The charge must be the 200ms block, not some 50ms fragment of the
        # paused region leaking out.
        assert _max_lag_ms(_report(pytester)) > 100.0

    def test_nested_pause_does_not_unpause_early(
        self, pytester: pytest.Pytester
    ) -> None:
        """A depth counter, not a boolean.

        A helper that pauses inside a caller's pause must leave the caller's
        window intact. The inner block is followed, still inside the outer
        window, by a real await -- so with a boolean the monitor gets a turn
        while it believes measurement has resumed, and charges the 150ms.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            def build_dependency():
                # A helper that scopes its own slow construction, unaware of
                # what its caller is doing.
                with loopguard_pause():
                    time.sleep(0.1)

            @pytest.mark.no_blocking
            async def test_nested_windows():
                with loopguard_pause():
                    build_dependency()
                    time.sleep(0.15)
                    # Still inside the OUTER window: nothing here may be
                    # recorded, even though the inner window has closed.
                    await asyncio.sleep(0.02)
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_exception_inside_pause_still_resumes_measurement(
        self, pytester: pytest.Pytester
    ) -> None:
        """The manager must use try/finally.

        An exception escaping the window must not leave measurement
        suppressed for the rest of the test -- that would turn one raising
        helper into a silently unguarded suite.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_raises_inside_then_blocks():
                with pytest.raises(RuntimeError):
                    with loopguard_pause():
                        raise RuntimeError("construction failed")
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_pause_under_loopguard_all_async(self, pytester: pytest.Pytester) -> None:
        """The harness switch is where the false positives came from.

        Under `loopguard_all_async` there is no marker to read, so the
        window has to work from the wrapper's own instrumentation -- and
        must still leave an unscoped blocking test flagged.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            async def test_setup_is_scoped_out():
                with loopguard_pause():
                    time.sleep(0.2)
                await asyncio.sleep(0.01)

            async def test_unscoped_still_flags():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_ALL_ASYNC_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, failed=1)


class TestLoopguardOnly:
    """`loopguard_only()`: measure this window and nothing else."""

    def test_only_ignores_setup_blocking(self, pytester: pytest.Pytester) -> None:
        """Setup blocking is cleared retroactively on first enter.

        The await after the setup block makes sure the monitor really did
        record it before the window opens -- otherwise this test would pass
        for the wrong reason. Retroactive clearing is safe because the
        pass/fail decision happens after the test body returns.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only

            @pytest.mark.no_blocking
            async def test_only_measures_the_window():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)  # the monitor records the stall here
                with loopguard_only():
                    await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_only_flags_blocking_inside_the_window(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only

            @pytest.mark.no_blocking
            async def test_handler_blocks():
                time.sleep(0.1)  # setup, deliberately out of scope
                with loopguard_only():
                    await asyncio.sleep(0.02)
                    time.sleep(0.2)
                    await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_only_suppresses_blocking_after_the_window(
        self, pytester: pytest.Pytester
    ) -> None:
        """Leaving the window suppresses the rest of the test.

        "Only this" has to mean teardown too, or the manager would only
        solve half of the reported problem.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only

            @pytest.mark.no_blocking
            async def test_teardown_is_out_of_scope():
                with loopguard_only():
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_second_only_window_reopens_without_clearing(
        self, pytester: pytest.Pytester
    ) -> None:
        """Only the FIRST enter clears.

        Nothing blocks between the two windows, so the run can only fail on
        the event the first window recorded. A second enter that cleared
        again would erase it and score the test clean.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only

            @pytest.mark.no_blocking
            async def test_two_windows():
                with loopguard_only():
                    await asyncio.sleep(0.02)
                    time.sleep(0.2)
                    await asyncio.sleep(0.02)
                with loopguard_only():
                    await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()
        assert _max_lag_ms(_report(pytester)) > 100.0

    def test_only_under_loopguard_all_async(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import asyncio
            import time

            from fastapi_loopguard.pytest_plugin import loopguard_only

            async def test_setup_out_of_scope():
                time.sleep(0.2)
                with loopguard_only():
                    await asyncio.sleep(0.01)

            async def test_unscoped_still_flags():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini(_TIGHT_ALL_ASYNC_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, failed=1)
