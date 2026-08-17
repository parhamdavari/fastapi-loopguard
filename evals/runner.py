"""Score one solution file against one eval task.

Usage:
    python evals/runner.py --task evals/tasks/01-user-lookup \
        --solution path/to/app.py [--out scores.json]

Copies the solution, the task's helpers and checks into a temp directory,
runs pytest there with LoopGuard's all-async gate and JSON report, and
reduces the result to a single score.

A verdict separates three states, never two: the solution ran and was clean,
the solution ran and blocked, or **the solution never ran** so blocking was
never observed. The third state is `measured: false` with `non_blocking:
null` — folding it into "did not block" is what lets a broken solution be
counted as evidence of non-blocking behaviour.

A solution counts as measured only when pytest executed at least one test
AND the task's trap helper was actually invoked. The second condition is
what catches a request rejected by FastAPI validation (HTTP 422) before the
endpoint body ever ran.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PYTEST_INI = """\
[pytest]
asyncio_mode = auto
loopguard_threshold_ms = 50
loopguard_all_async = true
loopguard_report = loopguard-report.json
"""

# Appended to the *copy* of helpers.py in the scoring workdir, never to the
# task file itself: the prompt the model sees must stay byte-identical to
# what is committed. Wraps every public helper so `helpers.calls()` counts
# trap invocations, which is how the scorer tells "ran and was clean" from
# "never ran". Private helpers are left alone, so a trap reached two frames
# deep (task 08) still counts exactly once, at its public entry point.
#
# The tally is a file, not a module global, because `run_in_executor` with a
# ProcessPoolExecutor is a correct answer here and runs the helper in a child
# process where a parent-process counter would never move. Counting in memory
# marks that solution as never having run.
HELPER_INSTRUMENTATION = '''

# --- appended by evals/runner.py; not part of the task fixture ---
_LOOPGUARD_CALL_LOG = {call_log!r}


def calls():
    """How many times a public helper ran, across every process."""
    import os

    try:
        return os.path.getsize(_LOOPGUARD_CALL_LOG)
    except OSError:
        return 0


def _loopguard_record():
    # One byte, O_APPEND: atomic enough across threads and processes, and the
    # size is the count. Microseconds, so it cannot perturb a 50 ms threshold.
    try:
        with open(_LOOPGUARD_CALL_LOG, "ab", buffering=0) as _fh:
            _fh.write(b".")
    except OSError:
        pass


def _loopguard_counted(_fn):
    import functools
    import inspect

    if inspect.iscoroutinefunction(_fn):

        @functools.wraps(_fn)
        async def _wrapper(*args, **kwargs):
            _loopguard_record()
            return await _fn(*args, **kwargs)

    else:

        @functools.wraps(_fn)
        def _wrapper(*args, **kwargs):
            _loopguard_record()
            return _fn(*args, **kwargs)

    return _wrapper


def _loopguard_instrument():
    import inspect
    import types

    for _name, _obj in list(globals().items()):
        if _name.startswith("_") or _name == "calls":
            continue
        if isinstance(_obj, types.FunctionType) and _obj.__module__ == __name__:
            globals()[_name] = _loopguard_counted(_obj)
        elif inspect.isclass(_obj) and _obj.__module__ == __name__:
            for _attr, _func in list(vars(_obj).items()):
                if _attr.startswith("_") or not isinstance(_func, types.FunctionType):
                    continue
                setattr(_obj, _attr, _loopguard_counted(_func))


_loopguard_instrument()
'''

# Records how many times the task's trap helper ran, so the scorer can tell
# "the endpoint ran and did not block" from "the endpoint never ran".
CONFTEST = '''\
"""Written by evals/runner.py. Records trap-helper invocations."""

import json
from pathlib import Path


def pytest_sessionfinish(session, exitstatus):
    calls = 0
    try:
        import helpers

        calls = int(helpers.calls())
    except Exception:  # helpers itself is broken; treat as never invoked
        calls = 0
    out = Path(__file__).parent / "helpers-calls.json"
    out.write_text(json.dumps({"calls": calls}))
'''

TIMEOUT_SECONDS = 120

# The subprocess runs untrusted generated code. Hand it only what Python
# needs, so API keys in the operator's environment are never exposed and a
# stray PYTEST_ADDOPTS / PYTHONPATH cannot alter the judge.
_ENV_ALLOWLIST = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TERM")


def _subprocess_env() -> dict[str, str]:
    """Minimal environment for the scoring subprocess."""
    return {name: os.environ[name] for name in _ENV_ALLOWLIST if name in os.environ}


def _tail(text: str, lines: int) -> list[str]:
    """Last `lines` non-empty-stripped lines of a stream."""
    return text.strip().splitlines()[-lines:]


def _record(
    task_dir: Path,
    *,
    score: int,
    measured: bool,
    non_blocking: bool | None,
    functional: bool | str,
    detail: str,
    flagged: list[str] | None = None,
    returncode: int | None = None,
    tests_run: int = 0,
    trap_calls: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, object]:
    """Assemble one verdict record."""
    return {
        "task": task_dir.name,
        "functional": functional,
        "non_blocking": non_blocking,
        "measured": measured,
        "score": score,
        "flagged": flagged or [],
        "detail": detail,
        "returncode": returncode,
        "tests_run": tests_run,
        "trap_calls": trap_calls,
        "pytest_tail": _tail(stdout, 3),
        "stderr_tail": _tail(stderr, 20),
    }


def score_task(task_dir: Path, solution: Path) -> dict[str, object]:
    """Run one task's checks against one solution; return the score record."""
    if not solution.read_text().strip():
        return _record(
            task_dir,
            score=0,
            measured=False,
            non_blocking=None,
            functional=False,
            detail="empty solution file: generation produced no code",
        )

    with tempfile.TemporaryDirectory(prefix="loopguard-eval-") as tmp:
        workdir = Path(tmp)
        shutil.copy(solution, workdir / "app.py")
        (workdir / "helpers.py").write_text(
            (task_dir / "helpers.py").read_text()
            + HELPER_INSTRUMENTATION.format(call_log=str(workdir / "helper-calls.log"))
        )
        shutil.copy(task_dir / "checks.py", workdir / "test_checks.py")
        (workdir / "pytest.ini").write_text(PYTEST_INI)
        (workdir / "conftest.py").write_text(CONFTEST)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--color=no"],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return _record(
                task_dir,
                score=0,
                measured=False,
                non_blocking=None,
                functional="unknown",
                detail=f"pytest timed out after {TIMEOUT_SECONDS}s",
            )

        report_path = workdir / "loopguard-report.json"
        blocked: list[str] = []
        tests_run = 0
        if report_path.exists():
            report = json.loads(report_path.read_text())
            tests_run = len(report["tests"])
            blocked = [
                record["nodeid"]
                for record in report["tests"]
                if record["verdict"] == "blocked"
            ]

        calls_path = workdir / "helpers-calls.json"
        trap_calls = 0
        if calls_path.exists():
            trap_calls = int(json.loads(calls_path.read_text())["calls"])

    common = {
        "returncode": proc.returncode,
        "tests_run": tests_run,
        "trap_calls": trap_calls,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }

    if tests_run == 0:
        return _record(
            task_dir,
            score=0,
            measured=False,
            non_blocking=None,
            functional=False,
            detail="no test ran: the solution failed to import or collect",
            **common,
        )

    if blocked:
        return _record(
            task_dir,
            score=0,
            measured=True,
            non_blocking=False,
            functional="unknown",
            detail=f"{len(blocked)} test(s) blocked the event loop",
            flagged=blocked,
            **common,
        )

    if trap_calls == 0:
        return _record(
            task_dir,
            score=0,
            measured=False,
            non_blocking=None,
            functional=False,
            detail=(
                "the trap helper was never invoked (rejected before the"
                " endpoint body, or the body never called it), so blocking"
                " could not be observed"
            ),
            **common,
        )

    if proc.returncode == 0:
        return _record(
            task_dir,
            score=1,
            measured=True,
            non_blocking=True,
            functional=True,
            detail="all checks passed without blocking",
            **common,
        )

    return _record(
        task_dir,
        score=0,
        measured=True,
        non_blocking=True,
        functional=False,
        detail="functional checks failed",
        **common,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--solution", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    for name in ("helpers.py", "checks.py"):
        if not (args.task / name).exists():
            parser.error(f"{args.task} is missing {name}")
    if not args.solution.exists():
        parser.error(f"solution not found: {args.solution}")

    result = score_task(args.task, args.solution)
    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        args.out.write_text(output)
    return 0 if result["score"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
