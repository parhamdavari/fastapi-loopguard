"""Ground-truth validation of the evals harness.

One full task scored against its known-clean and known-blocking reference
solutions, through the real runner CLI (which itself runs pytest in a
subprocess with the plugin's all-async gate).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RUNNER = REPO_ROOT / "evals" / "runner.py"
TASK = REPO_ROOT / "evals" / "tasks" / "01-user-lookup"


def _run(solution: Path) -> tuple[int, dict[str, object]]:
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--task",
            str(TASK),
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
        assert result["flagged"] == []

    def test_blocking_reference_scores_zero(self) -> None:
        returncode, result = _run(TASK / "reference" / "blocking.py")

        assert returncode == 1
        assert result["score"] == 0
        assert result["non_blocking"] is False
        assert len(result["flagged"]) == 1
        assert "test_returns_user" in result["flagged"][0]
