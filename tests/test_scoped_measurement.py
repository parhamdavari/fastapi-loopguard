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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

# Enable pytester fixture for plugin integration tests
pytest_plugins = ["pytester"]

from fastapi_loopguard import pytest_plugin  # noqa: E402
from fastapi_loopguard.pytest_plugin import REPORT_SCHEMA_VERSION  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO_ROOT / "docs" / "loopguard-report.schema.json"

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

# The route-unit end-to-end proof runs at the shipped default threshold:
# building the app costs ~110ms and the request it brackets costs ~1ms, so
# neither side of that comparison is close to 50ms.
_DEFAULT_INI = """
    [pytest]
    asyncio_mode = auto
    loopguard_threshold_ms = 50
"""


def _schema() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text())
    return parsed


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

    def test_only_window_block_without_trailing_await_still_flags(
        self, pytester: pytest.Pytester
    ) -> None:
        """The `only` mirror of the pause manager's no-trailing-await case.

        `test_only_flags_blocking_inside_the_window` above only holds
        because it awaits inside the window after the block, which lets the
        monitor take a turn. A real handler is under no obligation to yield
        there -- an `httpx.ASGITransport` request does not -- so the window
        has to stand on its own.

        Entering re-armed the tick and nothing measures it during the
        block; unless leaving banks that tick *before* it raises
        suppression, `stop()`'s final poll finds the window already closed
        and measures nothing. A 200ms stall inside the very region the user
        asked to measure, scored clean.
        """
        pytester.makepyfile("""
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only

            @pytest.mark.no_blocking
            async def test_only_window_block_no_trailing_await():
                # No await anywhere inside or after the window: leaving it
                # is the only chance to measure the stall.
                with loopguard_only():
                    time.sleep(0.2)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()
        assert _max_lag_ms(_report(pytester)) > 100.0

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


class TestScopedMeasurementNoOps:
    """Uninstrumented tests: both managers must be inert, not merely safe.

    A helper that scopes its own construction runs in every suite that
    imports it, most of which are not instrumented at all. If the managers
    needed a detector, they would either raise or warn there, and the
    helper could not be shared.
    """

    def test_no_op_in_a_synchronous_test(self, pytester: pytest.Pytester) -> None:
        """A sync test never runs on the event loop, so there is nothing
        to pause -- and nothing to complain about either."""
        pytester.makepyfile("""
            import time

            from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

            def test_sync():
                with loopguard_pause():
                    time.sleep(0.05)
                with loopguard_only():
                    time.sleep(0.05)
        """)
        pytester.makeini(_TIGHT_ALL_ASYNC_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_no_op_in_an_unmarked_async_test(self, pytester: pytest.Pytester) -> None:
        """No marker and the gate off: the wrapper never runs, so the
        context variable was never set."""
        pytester.makepyfile("""
            import asyncio
            import time

            from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

            async def test_unmarked():
                with loopguard_pause():
                    time.sleep(0.05)
                with loopguard_only():
                    time.sleep(0.05)
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_no_op_in_an_allow_blocking_test(self, pytester: pytest.Pytester) -> None:
        """`allow_blocking` means "not instrumented at all", so the
        managers have nothing to talk to even under the gate."""
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

            @pytest.mark.allow_blocking
            async def test_opted_out():
                with loopguard_pause():
                    time.sleep(0.05)
                with loopguard_only():
                    time.sleep(0.05)
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_ALL_ASYNC_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)

    def test_same_helper_passes_with_the_gate_on_and_off(
        self, pytester: pytest.Pytester
    ) -> None:
        """One suite, two runs, identical outcomes.

        The gate-off run is the one that matters: `passed=1, warnings=0`
        with nothing instrumenting the test proves the manager costs a
        shared helper nothing.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            async def build_app():
                # Shared helper: identical code under either gate setting.
                with loopguard_pause():
                    time.sleep(0.2)
                await asyncio.sleep(0.01)

            async def test_uses_the_shared_helper():
                await build_app()
        """)
        pytester.makeini(_TIGHT_INI)

        gate_off = pytester.runpytest("-v")
        gate_off.assert_outcomes(passed=1, warnings=0)

        gate_on = pytester.runpytest("-v", "--loopguard-all-async")
        gate_on.assert_outcomes(passed=1, warnings=0)

    def test_no_op_outside_an_instrumented_test(
        self, recwarn: pytest.WarningsRecorder
    ) -> None:
        """Used right here, in this repo's own uninstrumented suite.

        Yields immediately, raises nothing, warns nothing.
        """
        from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

        entered = []
        with loopguard_pause():
            entered.append("pause")
        with loopguard_only():
            entered.append("only")

        assert entered == ["pause", "only"]
        assert len(recwarn) == 0

    def test_no_op_outside_pytest_entirely(self) -> None:
        """A plain script, with no pytest session and no event loop.

        A subprocess is the only honest check: this process is mid-session,
        so an in-process assertion proves less than it looks like it does.
        """
        code = (
            "import time\n"
            "from fastapi_loopguard.pytest_plugin import (\n"
            "    loopguard_only,\n"
            "    loopguard_pause,\n"
            ")\n"
            "with loopguard_pause():\n"
            "    time.sleep(0.01)\n"
            "with loopguard_only():\n"
            "    time.sleep(0.01)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""


class TestScopedMeasurementInSpawnedTasks:
    """A child task inherits a context copy pointing at the same detector."""

    def test_pause_inside_a_task_spawned_by_the_test(
        self, pytester: pytest.Pytester
    ) -> None:
        """Scoping from inside a spawned task still works.

        `asyncio.create_task` copies the current context, so the child sees
        the same detector object. The window state therefore has to live on
        that object, not in a separate context variable the child would
        only be mutating its own copy of.
        """
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            async def build_in_a_task():
                with loopguard_pause():
                    time.sleep(0.2)
                await asyncio.sleep(0.01)

            @pytest.mark.no_blocking
            async def test_pause_from_a_child_task():
                await asyncio.create_task(build_in_a_task())
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)


class TestScopedMeasurementReport:
    """The JSON report is unchanged: a paused window produces no events."""

    def test_paused_window_produces_no_events(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import asyncio
            import time

            import pytest

            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_setup_is_scoped_out():
                with loopguard_pause():
                    time.sleep(0.2)
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(_TIGHT_INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(passed=1)

        report = _report(pytester)
        jsonschema.validate(report, _schema())
        assert report["schema_version"] == REPORT_SCHEMA_VERSION
        assert report["status"] == "clean"
        assert report["totals"] == {"tests": 1, "flagged": 0}

        (record,) = report["tests"]
        assert record["verdict"] == "clean"
        assert record["events"] == []
        assert record["hints"] == []


# A real FastAPI app, built the way the field report's 55 tests build one:
# inside the test body, per test. ~110ms of Pydantic validator and OpenAPI
# schema construction, none of which recurs in the deployed service, which
# builds the app once at process startup.
_APP_FACTORY_SOURCE = '''
"""A route-unit suite's app factory, of the shape issue #85 describes."""

from fastapi import FastAPI
from pydantic import BaseModel


class Address(BaseModel):
    street: str
    city: str
    postcode: str
    country: str = "NL"


class Profile(BaseModel):
    display_name: str
    bio: str | None = None
    address: Address
    tags: list[str] = []


class User(BaseModel):
    id: int
    email: str
    profile: Profile
    scores: dict[str, float] = {}
    active: bool = True


class Order(BaseModel):
    id: int
    user: User
    total: float
    lines: list[dict[str, str]] = []


class Invoice(BaseModel):
    id: int
    order: Order
    paid: bool = False


class Report(BaseModel):
    generated_for: User
    invoices: list[Invoice] = []
    totals: dict[str, float] = {}


MODELS = [Address, Profile, User, Order, Invoice, Report]


def create_app():
    """Build the app: Pydantic validators plus the OpenAPI schema."""
    app = FastAPI()

    for index, model in enumerate(MODELS * 30):
        async def read(item_id: int):
            return {"item_id": item_id}

        app.get(f"/g{index}/{{item_id}}", response_model=model)(read)

        async def write(payload: model):
            return payload

        app.post(f"/g{index}", response_model=model)(write)

    @app.get("/health")
    async def health():
        return {"ok": True}

    app.openapi()
    return app
'''


class TestRouteUnitSuiteRegression:
    """The end-to-end proof for #85, in the shape the report describes.

    A route-unit test builds a fresh app in its own body and then issues one
    clean request. The request is what the test is about; the construction
    is not. Today the plugin measures both and fails the test.

    Every test here uses `runpytest_subprocess`, never the in-process
    `runpytest` used elsewhere in this file. Pytester restores `sys.modules`
    after each in-process run, so a second run that imports FastAPI ends up
    holding routes built against one copy of `starlette.routing` and
    comparing them against another copy's `Match` enum: no route ever
    matches and every request 307s to its own path plus a slash. That is an
    artifact of nesting sessions, nothing to do with loopguard, and a fresh
    interpreter per run removes it.
    """

    def test_app_built_in_the_test_body_is_flagged_today(
        self, pytester: pytest.Pytester
    ) -> None:
        """Characterization test: this is the false positive itself.

        Passes today and must keep passing -- it is what makes the next
        test meaningful. Nothing here blocks a handler; the entire stall is
        app construction, and the request that follows is genuinely clean.
        """
        pytester.syspathinsert()
        pytester.makepyfile(appfactory=_APP_FACTORY_SOURCE)
        pytester.makepyfile("""
            import httpx
            import pytest

            from appfactory import create_app

            @pytest.mark.no_blocking
            async def test_health_route():
                app = create_app()
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    response = await client.get("/health")
                assert response.status_code == 200
        """)
        pytester.makeini(_DEFAULT_INI)

        result = pytester.runpytest_subprocess("-v", timeout=60)
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_scoping_construction_with_pause_clears_the_false_positive(
        self, pytester: pytest.Pytester
    ) -> None:
        """The same test, with construction scoped out, passes.

        One line changed against the test above. The request is still fully
        measured: a handler that blocked would still fail this test.
        """
        pytester.syspathinsert()
        pytester.makepyfile(appfactory=_APP_FACTORY_SOURCE)
        pytester.makepyfile("""
            import httpx
            import pytest

            from appfactory import create_app
            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_health_route():
                with loopguard_pause():
                    app = create_app()
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    response = await client.get("/health")
                assert response.status_code == 200
        """)
        pytester.makeini(_DEFAULT_INI)

        result = pytester.runpytest_subprocess("-v", timeout=60)
        result.assert_outcomes(passed=1, warnings=0)

    def test_a_blocking_handler_inside_the_measured_request_still_flags(
        self, pytester: pytest.Pytester
    ) -> None:
        """Scoping construction out must not scope the handler out.

        The handler under test blocks for 200ms; the app is built inside a
        `loopguard_pause()` exactly as above. The verdict has to be
        `blocked`, and on the handler's stall, not the construction's.
        """
        pytester.syspathinsert()
        pytester.makepyfile(appfactory=_APP_FACTORY_SOURCE)
        pytester.makepyfile("""
            import time

            import httpx
            import pytest

            from appfactory import create_app
            from fastapi_loopguard.pytest_plugin import loopguard_pause

            @pytest.mark.no_blocking
            async def test_slow_handler():
                with loopguard_pause():
                    app = create_app()

                    @app.get("/slow")
                    async def slow():
                        time.sleep(0.2)
                        return {"ok": True}

                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    response = await client.get("/slow")
                assert response.status_code == 200
        """)
        pytester.makeini(_DEFAULT_INI)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=60
        )
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

        report = _report(pytester)
        (record,) = report["tests"]
        assert record["verdict"] == "blocked"
        assert re.search(r"max lag: [\d.]+ms", result.stdout.str())
