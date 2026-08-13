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

Two runs, both through the OpenRouter gateway: the original run of
2026-08-12 and a free-model expansion of 2026-08-13. The five expansion
models were the top free coding models on OpenRouter that day, picked by
programming-category rank and weekly token volume. The ids below are the
exact model identifiers the provider returned. Every number traces to a
raw artifact under `evals/results/raw/`.

The benchmark's question is whether the one-sentence hint removes
event-loop blocking. A sample can also fail its functional checks for
unrelated reasons, so the headline below counts **blocking verdicts only**;
pass rates, which mix in functional failures, follow as context.

### Headline: blocking verdicts per condition (blocked/N)

| Model | Run date | Neutral | Hinted | Hint effect |
|---|---|---|---|---|
| `nvidia/nemotron-3.5-lightning:free` | 2026-08-12 | 5/40 (13%) | 0/40 (0%) | -13 pp |
| `openai/gpt-4.1` | 2026-08-12 | 21/40 (53%) | 0/40 (0%) | -53 pp |
| `poolside/laguna-s-2.1:free` | 2026-08-13 | 18/40 (45%) | 0/40 (0%) | -45 pp |
| `poolside/laguna-xs-2.1:free` | 2026-08-13 | 7/40 (18%) | 0/40 (0%) | -18 pp |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 2026-08-13 | 6/40 (15%) | 0/40 (0%) | -15 pp |
| `nvidia/nemotron-3-super-120b-a12b:free` | 2026-08-13 | 5/40 (13%) | 0/40 (0%) | -13 pp |
| `cohere/north-mini-code:free` | 2026-08-13 | 13/40 (33%) | 0/40 (0%) | -33 pp |

Across all seven models, not one of the 280 hinted samples ever blocked the
loop, while every model blocked in the neutral condition. N=5 samples per
(task, condition, model), 40 per cell above; temperature 1.0. Judge:
fastapi-loopguard 0.6.1 on Python 3.14.3, threshold 50 ms. Judge
self-check error rate on ground truth: 0/16 on every run.

### Where blocking happens (neutral condition, blocked/N)

| Task | lightning | gpt-4.1 | laguna-s | laguna-xs | ultra | super | north-mini |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 02-price-fanout | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 03-report-export | 0/5 | 5/5 | 4/5 | 0/5 | 1/5 | 0/5 | 2/5 |
| 04-image-thumbnail | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 |
| 05-audit-log | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 06-document-save | 0/5 | 5/5 | 3/5 | 0/5 | 1/5 | 0/5 | 3/5 |
| 07-legacy-billing | 0/5 | 1/5 | 2/5 | 0/5 | 0/5 | 0/5 | 3/5 |
| 08-order-pipeline | 0/5 | 5/5 | 4/5 | 2/5 | 0/5 | 0/5 | 0/5 |

The hinted-condition equivalent of this table is all zeros and is omitted.
Every blocking verdict of every model sits in the five tasks with no async
variant (03, 04, 06, 07, 08); tasks with an async twin (01, 02, 05) never
blocked for any model. Task 04 (CPU-bound thumbnail) defeats every model's
defaults.

### Context: overall pass rates (blocking AND functional failures)

These rates conflate the two failure kinds; the gap column is only
interpretable next to the per-task tables below and the blocking table
above.

| Model | Run date | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|---|
| `nvidia/nemotron-3.5-lightning:free` | 2026-08-12 | 24/40 (60%) | 24/40 (60%) | +0 pp |
| `openai/gpt-4.1` | 2026-08-12 | 16/40 (40%) | 39/40 (98%) | +57 pp |
| `poolside/laguna-s-2.1:free` | 2026-08-13 | 12/40 (30%) | 28/40 (70%) | +40 pp |
| `poolside/laguna-xs-2.1:free` | 2026-08-13 | 21/40 (52%) | 26/40 (65%) | +12 pp |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 2026-08-13 | 30/40 (75%) | 29/40 (72%) | -3 pp |
| `nvidia/nemotron-3-super-120b-a12b:free` | 2026-08-13 | 29/40 (72%) | 33/40 (82%) | +10 pp |
| `cohere/north-mini-code:free` | 2026-08-13 | 22/40 (55%) | 31/40 (78%) | +22 pp |

### Per-task breakdown (passed/N)

Neutral condition:

| Task | lightning | gpt-4.1 | laguna-s | laguna-xs | ultra | super | north-mini |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 02-price-fanout | 5/5 | 2/5 | 3/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 03-report-export | 5/5 | 0/5 | 1/5 | 4/5 | 3/5 | 5/5 | 2/5 |
| 04-image-thumbnail | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 05-audit-log | 0/5 | 5/5 | 1/5 | 1/5 | 4/5 | 4/5 | 3/5 |
| 06-document-save | 5/5 | 0/5 | 0/5 | 1/5 | 4/5 | 4/5 | 2/5 |
| 07-legacy-billing | 0/5 | 4/5 | 1/5 | 2/5 | 5/5 | 2/5 | 1/5 |
| 08-order-pipeline | 5/5 | 0/5 | 1/5 | 3/5 | 4/5 | 4/5 | 4/5 |

Hinted condition:

| Task | lightning | gpt-4.1 | laguna-s | laguna-xs | ultra | super | north-mini |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 02-price-fanout | 4/5 | 4/5 | 4/5 | 5/5 | 5/5 | 4/5 | 5/5 |
| 03-report-export | 3/5 | 5/5 | 4/5 | 3/5 | 3/5 | 5/5 | 4/5 |
| 04-image-thumbnail | 4/5 | 5/5 | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 |
| 05-audit-log | 1/5 | 5/5 | 1/5 | 1/5 | 2/5 | 4/5 | 4/5 |
| 06-document-save | 3/5 | 5/5 | 3/5 | 2/5 | 5/5 | 4/5 | 1/5 |
| 07-legacy-billing | 0/5 | 5/5 | 3/5 | 2/5 | 2/5 | 1/5 | 3/5 |
| 08-order-pipeline | 5/5 | 5/5 | 3/5 | 3/5 | 3/5 | 5/5 | 4/5 |

Column keys: `lightning` = `nvidia/nemotron-3.5-lightning:free`, `gpt-4.1`
= `openai/gpt-4.1`, `laguna-s` = `poolside/laguna-s-2.1:free`, `laguna-xs`
= `poolside/laguna-xs-2.1:free`, `ultra` =
`nvidia/nemotron-3-ultra-550b-a55b:free`, `super` =
`nvidia/nemotron-3-super-120b-a12b:free`, `north-mini` =
`cohere/north-mini-code:free`.

### What the pass-rate gap does and does not show

The pass-rate gap measures one thing: how far a model's *default* behavior sits from
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

Laguna S 2.1 — a dedicated coding model — replicates the GPT-4.1 shape more
strongly: all 18 of its neutral blocking verdicts sit in the five tasks
without an async variant (03, 04, 06, 07, 08), the hint eliminates every
one, and its remaining hinted failures are functional. Like Lightning, it
is near the floor on 05-audit-log in both conditions (1/5 and 1/5), so that
task reads as functional competence for this model too.

Laguna XS 2.1, the smaller Poolside model, is a Lightning-like case: its
+12 pp gap is compressed by functional failures that hit both conditions
alike (05, 06, 07 all at or near the floor twice). Its 7 neutral blocking
verdicts concentrate in tasks 04 and 08, and again the hint removes all of
them.

Nemotron 3 Ultra has the best measured defaults so far: 75% neutral, the
only model whose neutral rate beats its hinted rate. The -3 pp gap is not
+0-with-low-competence like Lightning; its neutral functional rate is
high, and its hinted losses (05, 07, 08) are functional regressions —
plausibly reasoning-model overengineering under an added constraint. Its
defaults are still not safe: 0/5 neutral on 04-image-thumbnail with 4
blocking verdicts, and 6 neutral blocking verdicts overall that the hint,
once again, eliminated completely.

Nemotron 3 Super blocks exactly like Lightning — all 5 of its neutral
blocking verdicts on 04-image-thumbnail — but with much higher functional
competence everywhere else, so its +10 pp pass-rate gap is almost entirely
the task 04 blocking fix (0/5 neutral, 5/5 hinted).

North Mini Code, despite being a dedicated coding model with the highest
programming rank of the free set, is the second-worst default blocker at
13/40 neutral, spread over four of the five no-async-variant tasks (03,
04, 06, 07). The hint removed all 13. Its one hinted regression,
06-document-save (3/5 neutral passes but 1/5 hinted), is functional, not
blocking.

### Limitations

- Eight tasks, all FastAPI, all single-endpoint. This is a single-domain,
  single-framework benchmark.
- Trap shapes are limited to the five listed above. Every trap simulates
  slowness with `time.sleep` inside a provided helper whose docstring says
  it is synchronous and slow — the benchmark tests *recognition* of a
  documented blocking API, not *discovery* of an undocumented one.
- N=5 per cell is small: one sample moves a per-task rate by 20 points and
  a per-condition aggregate by 2.5 points. Treat per-task rates as coarse.
- Results are point-in-time for the exact ids in the headline table, served
  via OpenRouter on the run date shown per row. A gateway may change the
  serving backend over time.
- The 2026-08-13 free-model runs were paced (6 s between requests, retry
  with backoff) after the gateway's security policy throttled burst
  traffic; generation for different models ran in parallel, but every
  pytest judge run was serialized through a file lock so the 50 ms timing
  measurement never shared the machine with another judge run.
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
# 2026-08-13 free-model expansion:
OPENROUTER_API_KEY=<your key> python evals/matrix.py \
  --models openrouter:poolside/laguna-s-2.1:free,openrouter:poolside/laguna-xs-2.1:free,openrouter:nvidia/nemotron-3-ultra-550b-a55b:free,openrouter:nvidia/nemotron-3-super-120b-a12b:free,openrouter:cohere/north-mini-code:free \
  --samples 5
```

Without any key, rebuild the tables from the committed raw artifacts:
`python evals/matrix.py --aggregate-only`.
