"""Score a matrix of (model, task, condition, sample) against the eval tasks.

Usage:
    python evals/matrix.py --models local:evals/results/solutions --samples 5
    python evals/matrix.py --models anthropic:claude-sonnet-5,openai:gpt-5

Flow:
  1. Judge self-check: every task's reference/clean.py must score 1 and
     reference/blocking.py must score 0. Any miscall aborts the run.
  2. Generation: each (model, task, condition, sample) is generated once and
     persisted verbatim under <results-dir>/raw/. Existing verdicts are
     skipped, so an interrupted run resumes where it stopped.
  3. Aggregation reads ONLY the raw artifacts on disk and rebuilds
     results.json and results.md. No number can appear in a table without a
     corresponding raw artifact.
"""

from __future__ import annotations

import argparse
import datetime
import json
import platform
import re
import sys
from collections import defaultdict
from importlib import metadata
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS_DIR))

import runner  # noqa: E402
from adapters import (  # noqa: E402
    Adapter,
    GenerationRequest,
    build_adapter,
    extract_code,
)

CONDITIONS = ("neutral", "hinted")
_match = re.search(r"loopguard_threshold_ms = (\d+)", runner.PYTEST_INI)
assert _match is not None
THRESHOLD_MS = int(_match.group(1))


def environment() -> dict[str, str | int]:
    """Run environment recorded with every result."""
    return {
        "python_version": platform.python_version(),
        "loopguard_version": metadata.version("fastapi-loopguard"),
        "threshold_ms": THRESHOLD_MS,
    }


def discover_tasks(only: list[str] | None = None) -> list[Path]:
    """Task directories under evals/tasks, optionally filtered by name."""
    tasks = sorted(
        path
        for path in (EVALS_DIR / "tasks").iterdir()
        if (path / "helpers.py").exists()
    )
    if only:
        by_name = {task.name: task for task in tasks}
        missing = [name for name in only if name not in by_name]
        if missing:
            raise SystemExit(f"unknown task(s): {', '.join(missing)}")
        tasks = [by_name[name] for name in only]
    return tasks


def self_check(tasks: list[Path]) -> dict[str, Any]:
    """Score both references of every task; the judge must call all of them."""
    errors: list[str] = []
    total = 0
    print("== judge self-check (ground truth) ==")
    for task in tasks:
        for ref, expected in (("clean", 1), ("blocking", 0)):
            total += 1
            verdict = runner.score_task(task, task / "reference" / f"{ref}.py")
            got = verdict["score"]
            ok = got == expected
            if ref == "blocking":
                ok = ok and verdict["non_blocking"] is False
            status = "ok" if ok else "MISCALL"
            print(f"  {task.name}/{ref}: expected {expected}, got {got} [{status}]")
            if not ok:
                errors.append(f"{task.name}/{ref}")
    rate = f"{len(errors)}/{total}"
    print(f"judge error rate on ground truth: {rate}")
    if errors:
        raise SystemExit(
            "ABORT: the judge miscalled its own references "
            f"({', '.join(errors)}); it cannot score models in this state."
        )
    return {"total": total, "errors": errors, "error_rate": rate}


def build_prompt(task_dir: Path, condition: str) -> str:
    """Assemble the model prompt: task text plus the shared context files."""
    task_text = (task_dir / condition / "task.md").read_text()
    skeleton = (task_dir / "app_skeleton.py").read_text()
    helpers = (task_dir / "helpers.py").read_text()
    return (
        f"{task_text}\n"
        f"\n## app_skeleton.py\n```python\n{skeleton}```\n"
        f"\n## helpers.py\n```python\n{helpers}```\n"
        "\nRespond with the complete contents of `app.py` in a single fenced"
        " Python code block. No explanation is needed."
    )


def slug(name: str) -> str:
    """Filesystem-safe directory name for a model spec."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def generate_matrix(
    adapters: list[Adapter],
    tasks: list[Path],
    conditions: list[str],
    samples: int,
    temperature: float,
    raw_dir: Path,
) -> list[str]:
    """Generate and score every missing cell sample. Returns skipped models."""
    skipped: list[str] = []
    for adapter in adapters:
        reason = adapter.unavailable_reason()
        if reason:
            print(f"SKIP model {adapter.name}: {reason}")
            skipped.append(f"{adapter.name}: {reason}")
            continue
        for task_dir in tasks:
            for condition in conditions:
                prompt = build_prompt(task_dir, condition)
                cell_dir = raw_dir / slug(adapter.name) / task_dir.name / condition
                cell_dir.mkdir(parents=True, exist_ok=True)
                for sample in range(1, samples + 1):
                    verdict_path = cell_dir / f"sample-{sample}.verdict.json"
                    if verdict_path.exists():
                        continue  # resumable: already generated and scored
                    request = GenerationRequest(
                        prompt=prompt,
                        task=task_dir.name,
                        condition=condition,
                        sample=sample,
                        temperature=temperature,
                    )
                    try:
                        result = adapter.generate(request)
                    except Exception as exc:  # noqa: BLE001 - keep the run alive
                        print(
                            f"ERROR {adapter.name} {task_dir.name}/{condition}"
                            f"/sample-{sample}: {exc}"
                        )
                        continue
                    response_path = cell_dir / f"sample-{sample}.response.txt"
                    solution_path = cell_dir / f"sample-{sample}.py"
                    response_path.write_text(result.text)
                    solution_path.write_text(extract_code(result.text))
                    verdict = runner.score_task(task_dir, solution_path)
                    record: dict[str, Any] = {
                        **verdict,
                        "requested_model": adapter.name,
                        "returned_model_id": result.model_id,
                        "condition": condition,
                        "sample": sample,
                        "temperature": temperature,
                        "run_date": datetime.datetime.now(datetime.UTC).isoformat(
                            timespec="seconds"
                        ),
                        **environment(),
                    }
                    verdict_path.write_text(json.dumps(record, indent=2))
                    print(
                        f"{adapter.name} {task_dir.name}/{condition}"
                        f"/sample-{sample}: score={record['score']}"
                        f" non_blocking={record['non_blocking']}"
                    )
    return skipped


def load_records(raw_dir: Path) -> list[dict[str, Any]]:
    """Every verdict record on disk — the only source of aggregate numbers."""
    return [
        json.loads(path.read_text())
        for path in sorted(raw_dir.glob("*/*/*/sample-*.verdict.json"))
    ]


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-cell and per-model rates, computed only from persisted records."""
    cells: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (record["requested_model"], record["task"], record["condition"])
        cells[key].append(record)

    def rates(group: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(group)
        passed = sum(1 for r in group if r["score"] == 1)
        blocked = sum(1 for r in group if not r["non_blocking"])
        functional_fail_only = sum(
            1 for r in group if r["non_blocking"] and r["score"] == 0
        )
        return {
            "n": n,
            "passed": passed,
            "pass_rate": passed / n if n else None,
            "blocked": blocked,
            "blocked_rate": blocked / n if n else None,
            "functional_fail_only": functional_fail_only,
        }

    cell_rows = [
        {"model": model, "task": task, "condition": condition, **rates(group)}
        for (model, task, condition), group in sorted(cells.items())
    ]

    by_model_condition: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_model_condition[(record["requested_model"], record["condition"])].append(
            record
        )
    model_rows = [
        {"model": model, "condition": condition, **rates(group)}
        for (model, condition), group in sorted(by_model_condition.items())
    ]
    return {"cells": cell_rows, "models": model_rows}


def fmt_rate(row: dict[str, Any] | None) -> str:
    """`k/n (xx%)` for a rate row, or `not run`."""
    if row is None or not row["n"]:
        return "not run"
    return f"{row['passed']}/{row['n']} ({100 * row['pass_rate']:.0f}%)"


def render_markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    """Headline table plus per-task breakdown, from aggregated records only."""
    models = sorted({row["model"] for row in summary["models"]})
    by_mc = {(r["model"], r["condition"]): r for r in summary["models"]}
    lines = [
        "# Results",
        "",
        "| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |",
        "|---|---|---|---|",
    ]
    for model in models:
        neutral = by_mc.get((model, "neutral"))
        hinted = by_mc.get((model, "hinted"))
        if neutral and neutral["n"] and hinted and hinted["n"]:
            gap = f"{100 * (hinted['pass_rate'] - neutral['pass_rate']):+.0f} pp"
        else:
            gap = "not run"
        lines.append(f"| {model} | {fmt_rate(neutral)} | {fmt_rate(hinted)} | {gap} |")
    lines += [
        "",
        f"Samples per (task, condition): N={meta['samples']};"
        f" temperature={meta['temperature']}; run date {meta['generated_at']}.",
        f"Environment: Python {meta['environment']['python_version']},"
        f" fastapi-loopguard {meta['environment']['loopguard_version']},"
        f" threshold {meta['environment']['threshold_ms']} ms.",
        f"Judge self-check error rate: {meta['judge_self_check']['error_rate']}.",
        "",
        "## Per-task breakdown (passed/n)",
        "",
    ]
    tasks = sorted({row["task"] for row in summary["cells"]})
    by_cell = {(r["model"], r["task"], r["condition"]): r for r in summary["cells"]}
    header = "| Task | " + " | ".join(
        f"{model} {condition}" for model in models for condition in CONDITIONS
    )
    lines += [header + " |", "|---|" + "---|" * (2 * len(models))]
    for task in tasks:
        row = [task]
        for model in models:
            for condition in CONDITIONS:
                cell = by_cell.get((model, task, condition))
                row.append(f"{cell['passed']}/{cell['n']}" if cell else "not run")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated specs: anthropic:<model>, openai:<model>,"
        " openrouter:<model>, local:<dir>",
    )
    parser.add_argument("--tasks", default=None, help="comma-separated task names")
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--results-dir", type=Path, default=EVALS_DIR / "results")
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="rebuild results.json/results.md from existing raw artifacts",
    )
    args = parser.parse_args()

    tasks = discover_tasks(args.tasks.split(",") if args.tasks else None)
    conditions = args.conditions.split(",")
    raw_dir = args.results_dir / "raw"

    check: dict[str, Any] = {"total": 0, "errors": [], "error_rate": "not run"}
    skipped: list[str] = []
    if not args.aggregate_only:
        if not args.models:
            parser.error("--models is required unless --aggregate-only is given")
        check = self_check(tasks)
        adapters = [build_adapter(spec) for spec in args.models.split(",")]
        skipped = generate_matrix(
            adapters, tasks, conditions, args.samples, args.temperature, raw_dir
        )

    records = load_records(raw_dir)
    if not records:
        print("no verdict records under", raw_dir)
        return 1
    summary = aggregate(records)
    meta = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(
            timespec="seconds"
        ),
        "samples": args.samples,
        "temperature": args.temperature,
        "environment": environment(),
        "judge_self_check": check,
        "skipped_models": skipped,
    }
    results = {"meta": meta, **summary, "records": records}
    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / "results.json").write_text(json.dumps(results, indent=2))
    markdown = render_markdown(summary, meta)
    (args.results_dir / "results.md").write_text(markdown)
    print(markdown)
    print(f"wrote {args.results_dir / 'results.json'} and results.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
