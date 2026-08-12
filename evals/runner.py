"""Score one solution file against one eval task.

Usage:
    python evals/runner.py --task evals/tasks/01-user-lookup \
        --solution path/to/app.py [--out scores.json]

Copies the solution, the task's helpers and checks into a temp directory,
runs pytest there with LoopGuard's all-async gate and JSON report, and
reduces the result to a single score.
"""

from __future__ import annotations

import argparse
import json
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


def score_task(task_dir: Path, solution: Path) -> dict[str, object]:
    """Run one task's checks against one solution; return the score record."""
    with tempfile.TemporaryDirectory(prefix="loopguard-eval-") as tmp:
        workdir = Path(tmp)
        shutil.copy(solution, workdir / "app.py")
        shutil.copy(task_dir / "helpers.py", workdir / "helpers.py")
        shutil.copy(task_dir / "checks.py", workdir / "test_checks.py")
        (workdir / "pytest.ini").write_text(PYTEST_INI)

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--color=no"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=120,
        )

        report_path = workdir / "loopguard-report.json"
        blocked: list[str] = []
        if report_path.exists():
            report = json.loads(report_path.read_text())
            blocked = [
                record["nodeid"]
                for record in report["tests"]
                if record["verdict"] == "blocked"
            ]

    non_blocking = not blocked
    passed = proc.returncode == 0

    if passed:
        detail = "all checks passed without blocking"
        functional: bool | str = True
    elif blocked:
        detail = f"{len(blocked)} test(s) blocked the event loop"
        functional = "unknown"
    else:
        detail = "functional checks failed"
        functional = False

    return {
        "task": task_dir.name,
        "functional": functional,
        "non_blocking": non_blocking,
        "score": 1 if passed else 0,
        "flagged": blocked,
        "detail": detail,
        "pytest_tail": proc.stdout.strip().splitlines()[-3:],
    }


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
