# LoopGuard Evals

A benchmark that measures whether an AI model writes **non-blocking** async
FastAPI code — and whether it does so *by default* or only when told to.
Each task ships a feature-request prompt, a provided `helpers.py` containing
a blocking trap, functional checks, and two ground-truth reference solutions;
LoopGuard's pytest plugin is the judge (50 ms threshold, deterministic
against the 120–150 ms traps).

## Two prompt conditions

Every task has the same skeleton, helpers, and checks under two prompts:

- `neutral/task.md` — the feature request only.
- `hinted/task.md` — byte-identical, plus one line: "The endpoint must not
  block the event loop."

The two files differ by **exactly that one added line** on all eight tasks, and
nothing else — not the title, not the spec, not a second hint naming the trap.
`make check-symmetry` below is the guard; if a condition pair ever differs by
more, the gap between them stops being attributable to the hint.

The neutral condition is the realistic one: a developer asks for an endpoint,
not for a non-blocking endpoint. The gap between the two conditions is the
headline metric.

**What the neutral prompt does still say.** The prompt is the task text plus
`app_skeleton.py` plus the full source of `helpers.py`, and those helper
docstrings describe the trap: "Synchronous: ~150ms of blocking I/O",
"synchronous only". On tasks 01, 02 and 05 the model is also handed a working
async twin. So the neutral condition is *easier* than a real codebase, where
nobody labels the blocking call. Read the neutral blocking rates as a floor.

## Trap shapes

The eight tasks cover five shapes. A plain `def` route is correct on **every**
task — FastAPI runs sync routes in a threadpool, which is exactly the right
answer — so it is never the distinguishing strategy:

| Tasks | Shape | Correct strategies |
|---|---|---|
| 01, 02, 05 | slow sync helper with an async twin (02 adds a latency budget that forces concurrent fetching) | async variant, `asyncio.to_thread`, or a plain `def` route |
| 03, 04 | slow sync helper, **no async variant** | `asyncio.to_thread` / executor, or a plain `def` route |
| 06 | blocking file I/O helper, no async variant | `asyncio.to_thread` / executor, or a plain `def` route |
| 07 | sync-only client object behind a FastAPI dependency | offload the method call, or a plain `def` route |
| 08 | blocking call two frames deep inside an innocent-looking helper | offload the top-level call, or a plain `def` route |

Every trap simulates its work with `time.sleep`, which **releases the GIL**.
That is a real limit on what these tasks can show: for genuinely CPU-bound
work a plain `def` route would starve the loop once enough requests arrive in
parallel, and this benchmark would still score it clean. What the tasks
measure is recognition of a documented slow synchronous call, not the
threadpool's behaviour under real CPU load.

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
pip install -r evals/requirements.txt

# Score one solution file against one task (single-file contract, unchanged):
python evals/runner.py --task evals/tasks/01-user-lookup --solution path/to/app.py

# Score a full matrix against API models (keys come from environment
# variables only: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY):
python evals/matrix.py --models anthropic:claude-sonnet-5,openai:gpt-5 --samples 5

# Re-judge every persisted solution without regenerating anything. Free: no
# API calls. Use after any judge change so old verdicts do not stay frozen.
python evals/matrix.py --rescore

# No API keys? The local adapter is the supported fallback. Generate
# solutions elsewhere, drop them in <dir>/<task>/<condition>/sample-<n>.py:
python evals/matrix.py --models local:path/to/solutions --samples 5
```

`evals/requirements.txt` is not optional for scoring. It carries
`python-multipart` and `aiofiles`, which some *solutions* import: without them
the judge fails the sample at import time and the harness's missing dependency
is published as the model's mistake.

Requests to one provider are paced (`--request-interval`, default 6 s for
OpenRouter, whose WAF rejects burst traffic) and retried with exponential
backoff. An empty completion is retried and then raised, never written out as
an empty `app.py`: a gateway returning nothing is an API failure, not a model
failure, and scoring it as one is how a provider hiccup becomes a published
pass rate.

Every matrix run starts with a **judge self-check**: all reference solutions
are re-scored, the judge's error rate on ground truth is printed and recorded
in `results.json`, and any miscall aborts the run. Runs are resumable — a
cell whose verdict already exists under `results/raw/` is skipped. Note that
`results.json` keeps only the *last* self-check of a batch, so "0/16" is a
statement about the runs on record, not about every invocation.

Condition symmetry is checkable in one line — it must print nothing:

```bash
for t in evals/tasks/*/; do
  diff <(cat "$t/neutral/task.md") <(cat "$t/hinted/task.md") \
    | grep -v '^[0-9]' | grep -v 'must not block the event loop' | grep '^[<>]'
done
```

A model whose SDK or key is missing is skipped with a message; the run
continues. Keys are never written to files or printed.

Each verdict record carries the exact model id returned by the provider, the
temperature, the sample index, the run date, the LoopGuard version, the
Python version, and the threshold used.

## Scoring semantics

Per sample, `runner.py` copies the solution, helpers, and checks into a temp
directory and runs pytest with `loopguard_all_async = true`:

| outcome | measured | non_blocking | score |
|---|---|---|---|
| all checks passed | true | true | 1 |
| ≥1 blocked verdict | true | **false** | 0 |
| ran, no blocking, functional failure | true | true | 0 |
| solution did not import, or was empty | **false** | **null** | 0 |
| trap helper never invoked (rejected before the body, or never called) | **false** | **null** | 0 |
| pytest timed out | **false** | **null** | 0 |

**`measured` is the important column.** A sample that never ran its endpoint
was never tested for blocking, so it is `null`, not `true`, and it is dropped
from every blocked-rate denominator. Recording it as "did not block" is a
one-directional bias: it can only ever make a model look better at the exact
number this benchmark publishes.

To tell "ran and was clean" from "never ran", the runner appends a counter to
its *copy* of `helpers.py` — never to the task fixture, so the prompt stays
byte-identical — and requires the trap to have actually executed. The tally is
a file rather than a module global, because `run_in_executor` with a
`ProcessPoolExecutor` is a correct answer here and runs the helper in a child
process.

Each `checks.py` also asserts the trap ran, so a solution that hardcodes the
expected response cannot score as functional *and* non-blocking. Six of the
eight tasks have a response body that is derivable from the request alone.

The matrix reports pass rates (score = 1) per (task, condition) and in
aggregate, plus the blocked rate separately, so a functional failure is not
mistaken for a blocking failure.

## Results

Seven models, all served through the OpenRouter gateway. The ids below are the
exact identifiers the provider returned, and every number traces to a raw
artifact under `evals/results/raw/`.

The benchmark's question is whether one sentence of instruction removes
event-loop blocking. A sample can also fail its functional checks for unrelated
reasons, so the headline counts **blocking verdicts only**; pass rates, which
mix in functional failures, follow as context.

Denominators are **measured** samples — those whose endpoint actually ran. 105
of the 560 generated samples never reached the blocking call (the request was
rejected before the endpoint body, the solution failed to import, or the
provider returned nothing), so they say nothing about blocking either way and
are excluded. The `Unmeasured` column reports how many that was.

### Headline: blocking verdicts per condition (blocked/measured)

| Model | Neutral | Hinted | Unmeasured (neutral/hinted) |
|---|---|---|---|
| `openai/gpt-4.1` | 21/37 (57%) | 0/40 (0%) | 3/0 |
| `poolside/laguna-s-2.1:free` | 18/38 (47%) | 0/32 (0%) | 2/8 |
| `cohere/north-mini-code:free` | 7/32 (22%) | 0/31 (0%) | 8/9 |
| `poolside/laguna-xs-2.1:free` | 5/30 (17%) | 0/30 (0%) | 10/10 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 5/33 (15%) | 0/33 (0%) | 7/7 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 3/38 (8%) | 0/33 (0%) | 2/7 |
| `nvidia/nemotron-3.5-lightning:free` | 1/25 (4%) | 0/23 (0%) | 15/17 |

**Pooled: 60 of 233 measured neutral samples blocked the event loop. Zero of
222 hinted samples did.** Every model blocked at least once by default; no
model blocked once told not to.

N=5 per (task, condition, model); temperature 1.0. Judge: fastapi-loopguard
0.6.1 on Python 3.14.3, threshold 50 ms. Judge self-check on ground truth:
0/16 on every recorded run. All 560 records carry the requested model id back
unchanged — no gateway substitution.

### Where blocking happens (neutral, blocked/measured)

| Task | gpt-4.1 | laguna-s | north-mini | laguna-xs | super | ultra | lightning |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/4 |
| 02-price-fanout | 0/2 | 0/3 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 03-report-export | 5/5 | 4/5 | 0/3 | 0/5 | 1/3 | 0/5 | 0/2 |
| 04-image-thumbnail | 5/5 | 5/5 | 1/1 | 3/3 | 4/4 | 2/5 | 1/4 |
| 05-audit-log | 0/5 | 0/5 | 0/4 | 0/1 | 0/5 | 0/4 | 0/0 |
| 06-document-save | 5/5 | 3/5 | 3/5 | 0/4 | 0/4 | 1/5 | 0/5 |
| 07-legacy-billing | 1/5 | 2/5 | 3/5 | 0/2 | 0/2 | 0/5 | 0/0 |
| 08-order-pipeline | 5/5 | 4/5 | 0/4 | 2/5 | 0/5 | 0/4 | 0/5 |

The hinted equivalent of this table is all zeros and is omitted.

Two cells are `0/0`: Lightning's 05-audit-log and 07-legacy-billing neutral
samples all failed before reaching the helper, so nothing was measured there.
`0/0` means "no evidence", not "clean" — read those two as blank, and treat
any cell with a small denominator as coarse.

Every blocking verdict, for every model, sits in the five tasks with no async
variant (03, 04, 06, 07, 08). Tasks 01, 02 and 05 hand the model a working
async twin and have never produced a blocking verdict in either condition —
they measure whether a model picks up the async variant, not whether it
offloads. 04-image-thumbnail is the hardest: every model blocks on it.

### What the failures actually look like

This is the sharpest result in the benchmark, and it is not a rate.

**All 60 neutral blocking verdicts have the identical shape:** an `async def`
route that calls the synchronous helper directly, with no offload. Not one is
anything else.

Meanwhile **81 passing neutral samples used a plain `def` route** — which
FastAPI runs in a threadpool, so it never blocks — against **1** in the hinted
condition.

So the default-condition failure is not "the model does not know about
`asyncio.to_thread`". Models split between two behaviours: write a plain `def`
route and be safe by construction, or reach for `async def` and then call
blocking code inside it. The hint does not teach offloading so much as it makes
the model notice which of the two it just chose. Under instruction, models
converge on `async def` plus an explicit offload, and the blocking disappears.

### Context: overall pass rates (blocking AND functional failures)

These conflate the two failure kinds, and every denominator here is all 40
generated samples, measured or not. The gap column is only interpretable next
to the tables above.

| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|
| `openai/gpt-4.1` | 16/40 (40%) | 40/40 (100%) | +60 pp |
| `poolside/laguna-s-2.1:free` | 12/40 (30%) | 24/40 (60%) | +30 pp |
| `nvidia/nemotron-3-super-120b-a12b:free` | 26/40 (65%) | 33/40 (82%) | +17 pp |
| `cohere/north-mini-code:free` | 23/40 (58%) | 27/40 (68%) | +10 pp |
| `poolside/laguna-xs-2.1:free` | 22/40 (55%) | 22/40 (55%) | +0 pp |
| `nvidia/nemotron-3.5-lightning:free` | 24/40 (60%) | 23/40 (58%) | -3 pp |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 35/40 (88%) | 33/40 (82%) | -5 pp |

A small or negative gap here does **not** mean good defaults. It usually means
functional failures dominate in both conditions, leaving the hint little to
fix. Nemotron 3 Ultra has the strongest functional competence in the set (88%
neutral) and still blocked on 3 measured neutral samples that the hint
eliminated. Lightning's -3 pp gap sits on top of the smallest measured base in
the set: only 25 of its 40 neutral samples ran at all.

### Per-task breakdown (passed/N of all 40)

Neutral:

| Task | gpt-4.1 | laguna-s | north-mini | laguna-xs | super | ultra | lightning |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 |
| 02-price-fanout | 2/5 | 3/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 03-report-export | 0/5 | 1/5 | 3/5 | 5/5 | 2/5 | 5/5 | 2/5 |
| 04-image-thumbnail | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 3/5 | 3/5 |
| 05-audit-log | 5/5 | 1/5 | 3/5 | 1/5 | 4/5 | 4/5 | 0/5 |
| 06-document-save | 0/5 | 0/5 | 2/5 | 1/5 | 4/5 | 4/5 | 5/5 |
| 07-legacy-billing | 4/5 | 1/5 | 1/5 | 2/5 | 2/5 | 5/5 | 0/5 |
| 08-order-pipeline | 0/5 | 1/5 | 4/5 | 3/5 | 4/5 | 4/5 | 5/5 |

Hinted:

| Task | gpt-4.1 | laguna-s | north-mini | laguna-xs | super | ultra | lightning |
|---|---|---|---|---|---|---|---|
| 01-user-lookup | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 |
| 02-price-fanout | 5/5 | 2/5 | 5/5 | 4/5 | 5/5 | 5/5 | 5/5 |
| 03-report-export | 5/5 | 4/5 | 3/5 | 3/5 | 4/5 | 5/5 | 0/5 |
| 04-image-thumbnail | 5/5 | 3/5 | 2/5 | 2/5 | 5/5 | 5/5 | 5/5 |
| 05-audit-log | 5/5 | 1/5 | 4/5 | 1/5 | 4/5 | 3/5 | 1/5 |
| 06-document-save | 5/5 | 3/5 | 1/5 | 2/5 | 4/5 | 5/5 | 3/5 |
| 07-legacy-billing | 5/5 | 3/5 | 3/5 | 2/5 | 1/5 | 2/5 | 0/5 |
| 08-order-pipeline | 5/5 | 3/5 | 4/5 | 3/5 | 5/5 | 3/5 | 5/5 |

Column keys: `gpt-4.1` = `openai/gpt-4.1`, `laguna-s` =
`poolside/laguna-s-2.1:free`, `north-mini` = `cohere/north-mini-code:free`,
`laguna-xs` = `poolside/laguna-xs-2.1:free`, `super` =
`nvidia/nemotron-3-super-120b-a12b:free`, `ultra` =
`nvidia/nemotron-3-ultra-550b-a55b:free`, `lightning` =
`nvidia/nemotron-3.5-lightning:free`.

### How strong is this, statistically?

Not as strong per model as the percentages suggest, and stronger in aggregate.

The five samples in a cell are the same prompt five times, and most cells come
out 0/5 or 5/5, so they are not five independent observations. The honest unit
is the **task**. Counting a task as "blocked" if any of its samples blocked:

| Model | Tasks blocked, neutral | Tasks blocked, hinted | Exact two-sided p |
|---|---|---|---|
| `openai/gpt-4.1` | 5 | 0 | 0.0625 |
| `poolside/laguna-s-2.1:free` | 5 | 0 | 0.0625 |
| `cohere/north-mini-code:free` | 3 | 0 | 0.250 |
| `poolside/laguna-xs-2.1:free` | 2 | 0 | 0.500 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 2 | 0 | 0.500 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 2 | 0 | 0.500 |
| `nvidia/nemotron-3.5-lightning:free` | 1 | 0 | 1.000 |

**No individual model reaches p < 0.05.** With 8 tasks it cannot: a sign test
needs 6 tasks moving together to get there, and the two strongest models sit at
the floor of what this design permits. Per-model percentage-point deltas should
not be quoted as if they were significant.

**Pooled across all seven models: 20 discordant (model, task) clusters, all 20
in the same direction, p ≈ 1.9e-06.** That is the claim this benchmark
supports — a statement about models and tasks in aggregate, not about any one
model's number.

### Provenance

| Tasks | Generated | Note |
|---|---|---|
| 03, 04 | 2026-08-16 | regenerated after the prompts were made condition-symmetric |
| 02 | 2026-08-12/13 neutral, 2026-08-16 hinted | hinted prompt was corrected |
| 01, 05, 06, 07, 08 | 2026-08-12/13 | prompts unchanged; re-judged in place |

An earlier version of this benchmark published different figures. Three things
were wrong with it, all fixed above, and the pre-correction artifacts remain in
git history:

1. **Samples that never ran were counted as "did not block."** A solution that
   failed to import, or whose request was rejected before the endpoint body,
   was recorded as non-blocking and kept in the denominator. That is a bias
   with only one direction, pointing at the headline number.
2. **Empty gateway responses were scored as model failures.** Fourteen samples
   were zero-byte completions written out as empty `app.py` files. They are now
   retried and then raised.
3. **Three tasks were not condition-symmetric.** Their hinted prompts carried a
   second hint naming the trap, and one pair had different functional specs
   entirely — so on the tasks carrying most of the signal, the measured gap was
   not attributable to the one-sentence hint. Task 04 also required FastAPI's
   `Request`, which forces `async def` and removed the plain-`def` escape that
   models use everywhere else.

The direction and the significance of the result survived all three fixes. The
per-model rates moved.

### Limitations

**Design**

- Eight tasks, all FastAPI, all single-endpoint. This is a single-domain,
  single-framework benchmark.
- Every trap simulates slowness with `time.sleep`, which releases the GIL, so
  the benchmark cannot distinguish threadpool offload from true CPU offload.
  See "Trap shapes" above.
- The trap is documented in the `helpers.py` the model is shown, so this tests
  *recognition* of a labelled blocking API, not *discovery* of an unlabelled
  one. Real code does not come with those docstrings.
- Tasks 01, 02 and 05 hand the model a working async twin, and 02's latency
  budget makes concurrency mandatory to pass at all. None of the three has
  ever produced a blocking verdict, in either condition, for any model. They
  measure whether the model picks up the async variant, not whether it
  offloads; the blocking signal lives entirely in 03, 04, 06, 07 and 08.
- Each task has exactly one functional check, issued as a single request.
  Blocking that only appears under concurrency, only after warm-up, or only in
  a lifespan startup handler is structurally invisible here.

**Statistics**

- N=5 per cell is small, and the five samples in a cell are not independent —
  they are the same prompt five times, and most cells come out 0/5 or 5/5. The
  honest unit of evidence is the **task**, of which there are 8, so effective
  N per model per condition is nearer 10 than 40.
- Consequently, per-model hint effects are not individually significant: with
  8 tasks, an exact task-level sign test cannot reach p < 0.05 unless 6 tasks
  move together. Read the aggregate across models, not per-model deltas.
- Rates are point-in-time for the exact ids in the headline table, served via
  OpenRouter on the run date shown per row. A gateway may change the serving
  backend over time; the backend provider is not recorded in the artifacts.

**Harness**

- Samples whose endpoint never ran are excluded from blocked-rate
  denominators, so those denominators are smaller than N and differ per model.
  The `Unmeasured` column reports how many were dropped.
- Scored on Python 3.14.3, outside the package's own 3.12/3.13 CI matrix.
- Generation is serial and paced; nothing else runs on the machine during a
  judge run, so the 50 ms timing measurement is not competing for CPU.
- The judge here is the pytest plugin's single-lag detector. It has **no
  cumulative-window detection**, unlike `LoopGuardMiddleware`'s defaults, so
  repeated sub-threshold blocking inside one request passes as clean. Every
  trap in this benchmark is 120–150 ms against a 50 ms threshold, so the
  margin is 2.4×, but the judge is weaker than the shipped middleware.
- No ground truth needed adjusting: all 16 reference solutions scored
  correctly on every self-check.

### Reproduction

```bash
pip install -e ".[dev]" && pip install -r evals/requirements.txt
export OPENROUTER_API_KEY=<your key>
python evals/matrix.py --samples 5 --models \
  openrouter:openai/gpt-4.1,\
openrouter:nvidia/nemotron-3.5-lightning:free,\
openrouter:poolside/laguna-s-2.1:free,\
openrouter:poolside/laguna-xs-2.1:free,\
openrouter:nvidia/nemotron-3-ultra-550b-a55b:free,\
openrouter:nvidia/nemotron-3-super-120b-a12b:free,\
openrouter:cohere/north-mini-code:free
```

Requests pace themselves at 6 s and retry with backoff, so the run takes
roughly an hour and needs no manual throttling. It is resumable: re-running
skips any cell that already has a verdict.

Without any key:

```bash
python evals/matrix.py --rescore          # re-judge the committed solutions
python evals/matrix.py --aggregate-only   # rebuild the tables only
```
