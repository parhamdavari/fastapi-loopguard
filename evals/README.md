# LoopGuard Evals

A benchmark that measures whether an AI model writes **non-blocking** async
FastAPI code — and whether it does so *by default* or only when told to.
Each task ships a feature-request prompt, a provided `helpers.py` containing
a blocking trap, functional checks, and two ground-truth reference solutions;
LoopGuard's pytest plugin is the judge (50 ms threshold, deterministic
against the 120–150 ms traps).

## Two prompt conditions

Every task has the same skeleton, helpers, and checks under two prompts:

- `neutral/task.md` — the feature request only. No mention of blocking, the
  event loop, async correctness, threads, or concurrency mechanisms.
- `hinted/task.md` — the same request plus the explicit constraint "the
  endpoint must not block the event loop".

The neutral condition is the realistic one: a developer asks for an endpoint,
not for a non-blocking endpoint. The gap between the two conditions is the
headline metric.

## Trap shapes

The eight tasks cover five shapes:

| Tasks | Shape | Correct strategies |
|---|---|---|
| 01, 02, 05 | slow sync helper with an async twin (02 adds a latency budget that forces concurrent fetching) | async variant, `asyncio.to_thread`, or a plain `def` route |
| 03, 04 | CPU-bound helper, **no async variant** | `asyncio.to_thread` / executor |
| 06 | blocking file I/O helper, no async variant | `asyncio.to_thread` / executor |
| 07 | sync-only client object behind a FastAPI dependency | offload the method call |
| 08 | blocking call two frames deep inside an innocent-looking helper | offload the top-level call |

## Layout

```
evals/
  runner.py                     score one solution against one task
  matrix.py                     score a (model x task x condition x sample) matrix
  adapters.py                   provider adapters: anthropic:, openai:, local:
  requirements.txt              SDKs for the API adapters (eval-only deps)
  tasks/<name>/
    neutral/task.md             prompt without the constraint
    hinted/task.md              prompt with the constraint
    app_skeleton.py             starting file the model completes
    helpers.py                  provided API (contains the trap)
    checks.py                   functional pytest checks
    reference/clean.py          known-good solution (ground truth)
    reference/blocking.py       known-blocking solution (ground truth)
  results/
    raw/<model>/<task>/<condition>/sample-<n>.*   every generated solution,
                                raw response, and verdict — the evidence
    results.json, results.md    aggregates, rebuilt only from raw/
```

`reference/` is ground truth for validating the judge — it is never included
in the context given to a model under test.

## Running

```bash
pip install -e ".[dev]"              # from the repository root

# Score one solution file against one task (single-file contract, unchanged):
python evals/runner.py --task evals/tasks/01-user-lookup --solution path/to/app.py

# Score a full matrix against API models (keys come from environment
# variables only: ANTHROPIC_API_KEY, OPENAI_API_KEY):
pip install -r evals/requirements.txt
python evals/matrix.py --models anthropic:claude-sonnet-5,openai:gpt-5 --samples 5

# No API keys? The local adapter is the supported fallback. Generate
# solutions elsewhere, drop them in <dir>/<task>/<condition>/sample-<n>.py:
python evals/matrix.py --models local:path/to/solutions --samples 5
```

Every matrix run starts with a **judge self-check**: all reference solutions
are re-scored, the judge's error rate on ground truth is printed and recorded
in `results.json`, and any miscall aborts the run. Runs are resumable — a
cell whose verdict already exists under `results/raw/` is skipped.

A model whose SDK or key is missing is skipped with a message; the run
continues. Keys are never written to files or printed.

Each verdict record carries the exact model id returned by the provider, the
temperature, the sample index, the run date, the LoopGuard version, the
Python version, and the threshold used.

## Scoring semantics

Per sample, `runner.py` copies the solution, helpers, and checks into a temp
directory and runs pytest with `loopguard_all_async = true`:

| exit | blocked verdicts | functional | non_blocking | score |
|------|------------------|------------|--------------|-------|
| 0    | none             | true       | true         | 1     |
| ≠0   | ≥1               | unknown    | false        | 0     |
| ≠0   | none             | false      | true         | 0     |

The matrix reports pass rates (score = 1) per (task, condition) and in
aggregate, plus the blocked rate separately, so a functional failure is not
mistaken for a blocking failure.

## Results

Run of 2026-08-12. Both models were accessed through the OpenRouter gateway;
the ids below are the exact model identifiers the provider returned. Every
number traces to a raw artifact under `evals/results/raw/`.

| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|
| `nvidia/nemotron-3.5-lightning:free` | 24/40 (60%) | 24/40 (60%) | +0 pp |
| `openai/gpt-4.1` | 16/40 (40%) | 39/40 (98%) | +57 pp |

N=5 samples per (task, condition, model), 40 per cell above; temperature 1.0;
run date 2026-08-12. Judge: fastapi-loopguard 0.6.1 on Python 3.14.3,
threshold 50 ms. Judge self-check error rate on ground truth: 0/16.

Blocked verdicts, reported separately from functional failures: GPT-4.1
blocked the loop in 21/40 neutral samples and 0/40 hinted; Nemotron blocked
in 5/40 neutral and 0/40 hinted. The rest of each model's failures were
functional (wrong or broken code without a blocking verdict).

### Per-task breakdown (passed/N)

| Task | nemotron neutral | nemotron hinted | gpt-4.1 neutral | gpt-4.1 hinted |
|---|---|---|---|---|
| 01-user-lookup | 4/5 | 4/5 | 5/5 | 5/5 |
| 02-price-fanout | 5/5 | 4/5 | 2/5 | 4/5 |
| 03-report-export | 5/5 | 3/5 | 0/5 | 5/5 |
| 04-image-thumbnail | 0/5 | 4/5 | 0/5 | 5/5 |
| 05-audit-log | 0/5 | 1/5 | 5/5 | 5/5 |
| 06-document-save | 5/5 | 3/5 | 0/5 | 5/5 |
| 07-legacy-billing | 0/5 | 0/5 | 4/5 | 5/5 |
| 08-order-pipeline | 5/5 | 5/5 | 0/5 | 5/5 |

### What the gap does and does not show

The gap measures one thing: how far a model's *default* behavior sits from
its *instructed* behavior on this specific skill. For GPT-4.1 the gap is
large and attributable to blocking: 21 of its 24 neutral failures were
blocking verdicts, concentrated entirely in the tasks with no async variant
(03, 04, 06, 08: 0/20 neutral, 20/20 hinted). The model reaches for an async
twin whenever one exists but does not offload sync work unprompted. The gap
does not measure general coding competence, and it is only interpretable
when functional pass rates are high: Nemotron's +0 pp gap does not mean good
defaults — it failed 16/40 samples in *both* conditions (11 functional and
5 blocking in neutral; all 16 functional in hinted), so the hint had little
left to fix. A small gap is not evidence
that a model is safe to leave unprompted; read it next to the per-task table.

### Limitations

- Eight tasks, all FastAPI, all single-endpoint. This is a single-domain,
  single-framework benchmark.
- Trap shapes are limited to the five listed above. Every trap simulates
  slowness with `time.sleep` inside a provided helper whose docstring says
  it is synchronous and slow — the benchmark tests *recognition* of a
  documented blocking API, not *discovery* of an undocumented one.
- N=5 per cell is small: one sample moves a per-task rate by 20 points and
  a per-condition aggregate by 2.5 points. Treat per-task rates as coarse.
- Results are point-in-time for the exact ids `openai/gpt-4.1` and
  `nvidia/nemotron-3.5-lightning:free`, served via OpenRouter on 2026-08-12.
  A gateway may change the serving backend over time.
- Two tasks are at or near the floor for Nemotron in both conditions
  (07-legacy-billing 0/10, 05-audit-log 1/10). For that model those tasks
  measure functional competence, not blocking defaults.
- Task 02's neutral prompt keeps a latency budget because the functional
  check enforces one; a latency budget may itself nudge toward concurrency.
- Scored on Python 3.14.3, outside the package's 3.12/3.13 CI matrix.
- No ground truth needed adjusting: all 16 reference solutions scored
  correctly on the first run and on every subsequent self-check.

### Reproduction

```bash
pip install -e ".[dev]" && pip install -r evals/requirements.txt
OPENROUTER_API_KEY=<your key> python evals/matrix.py \
  --models openrouter:openai/gpt-4.1,openrouter:nvidia/nemotron-3.5-lightning:free \
  --samples 5
```

Without any key, rebuild the tables from the committed raw artifacts:
`python evals/matrix.py --aggregate-only`.
