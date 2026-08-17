"""Ground-truth validation of the evals harness.

Two things are pinned here.

`TestEvalsGroundTruth` scores one full task against its known-clean and
known-blocking reference solutions, through the real runner CLI (which itself
runs pytest in a subprocess with the plugin's all-async gate).

`TestUnmeasuredSamples` pins the defect that reached a published table: a
solution that never ran was recorded as `non_blocking: true` and counted as
evidence that the model did not block. A sample is only evidence about blocking
if its endpoint actually reached the blocking call, so every way of failing to
get there must produce `non_blocking: None`, never `True`.

Each test runs a real pytest subprocess, so these are slower than the rest of
the suite. They are deliberately few, against two tasks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNNER = REPO_ROOT / "evals" / "runner.py"
TASK = REPO_ROOT / "evals" / "tasks" / "01-user-lookup"
PIPELINE_TASK = REPO_ROOT / "evals" / "tasks" / "08-order-pipeline"


def _run(solution: Path, task: Path = TASK) -> tuple[int, dict[str, object]]:
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--task",
            str(task),
            "--solution",
            str(solution),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
    )
    return proc.returncode, json.loads(proc.stdout)


class TestEvalsGroundTruth:
    """The harness must separate the reference solutions."""

    def test_clean_reference_scores_one(self) -> None:
        returncode, result = _run(TASK / "reference" / "clean.py")

        assert returncode == 0
        assert result["score"] == 1
        assert result["functional"] is True
        assert result["non_blocking"] is True
        assert result["measured"] is True
        assert result["flagged"] == []

    def test_blocking_reference_scores_zero(self) -> None:
        returncode, result = _run(TASK / "reference" / "blocking.py")

        assert returncode == 1
        assert result["score"] == 0
        assert result["non_blocking"] is False
        assert result["measured"] is True
        assert len(result["flagged"]) == 1
        assert "test_returns_user" in result["flagged"][0]


class TestUnmeasuredSamples:
    """A sample that never ran must never read as non-blocking."""

    def test_unimportable_solution(self, tmp_path: Path) -> None:
        solution = tmp_path / "app.py"
        solution.write_text("this is not python(\n")

        _, result = _run(solution)

        assert result["measured"] is False
        assert result["non_blocking"] is None  # never True: nothing was measured
        assert result["score"] == 0
        assert result["tests_run"] == 0

    def test_empty_solution(self, tmp_path: Path) -> None:
        solution = tmp_path / "app.py"
        solution.write_text("")

        _, result = _run(solution)

        assert result["measured"] is False
        assert result["non_blocking"] is None
        assert result["score"] == 0

    def test_solution_that_never_calls_the_helper(self, tmp_path: Path) -> None:
        # Functionally correct-looking, but the trap never runs, so the sample
        # says nothing about whether the model blocks.
        solution = tmp_path / "app.py"
        solution.write_text(
            "from fastapi import FastAPI\n"
            "\n"
            "import helpers  # noqa: F401\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "\n"
            '@app.post("/orders", status_code=201)\n'
            "async def create_order(order: dict) -> dict:\n"
            '    return {"item": order["item"], "reserved": True}\n'
        )

        _, result = _run(solution, PIPELINE_TASK)

        assert result["measured"] is False
        assert result["non_blocking"] is None
        assert result["score"] == 0
        assert result["trap_calls"] == 0

    @pytest.mark.parametrize("task", [TASK, PIPELINE_TASK])
    def test_offloading_to_a_process_pool_is_measured(
        self, tmp_path: Path, task: Path
    ) -> None:
        # The trap counter has to survive a process boundary. Counting in
        # memory would mark this correct solution as never having run.
        helper = "load_user" if task is TASK else "process_order"
        route = (
            '@app.get("/users/{user_id}")\nasync def read(user_id: int) -> dict:\n'
            if task is TASK
            else '@app.post("/orders", status_code=201)\n'
            "async def read(order: dict) -> dict:\n"
        )
        arg = "user_id" if task is TASK else "order"
        solution = tmp_path / "app.py"
        solution.write_text(
            "import asyncio\n"
            "from concurrent.futures import ProcessPoolExecutor\n"
            "\n"
            "from fastapi import FastAPI\n"
            "\n"
            "import helpers\n"
            "\n"
            "app = FastAPI()\n"
            "_pool = ProcessPoolExecutor()\n"
            "\n"
            "\n"
            f"{route}"
            "    loop = asyncio.get_running_loop()\n"
            f"    return await loop.run_in_executor(_pool, helpers.{helper}, {arg})\n"
        )

        _, result = _run(solution, task)

        assert result["measured"] is True
        assert result["non_blocking"] is True
        assert result["trap_calls"] >= 1
