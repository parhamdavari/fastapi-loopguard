# LoopGuard Evals

A small benchmark that scores whether an AI model writes **non-blocking**
async FastAPI code. Each task ships a prompt, a provided `helpers.py`, and
functional checks; LoopGuard's pytest plugin is the judge.

The trap is always the same shape: `helpers.py` offers a slow synchronous
function (and sometimes an async variant). A correct solution keeps the
event loop free — by using the async variant or wrapping the sync one in
`asyncio.to_thread` — while a naive solution calls the sync helper directly
and blocks the loop for 100–200 ms, which the plugin flags deterministically
against the 50 ms threshold.

## Layout

```
evals/
  runner.py                     score one solution against one task
  tasks/<name>/
    task.md                     the prompt to give the model
    app_skeleton.py             starting file the model completes
    helpers.py                  provided API (contains the trap)
    checks.py                   functional pytest checks
    reference/clean.py          known-good solution (ground truth)
    reference/blocking.py       known-blocking solution (ground truth)
```

`reference/` is ground truth for validating the harness — exclude it from
any context you give the model under test.

## Running

```bash
pip install -e ".[dev]"      # from the repository root

python evals/runner.py \
  --task evals/tasks/01-user-lookup \
  --solution path/to/model_output.py
```

Output (also written with `--out scores.json`):

```json
{
  "task": "01-user-lookup",
  "functional": true,
  "non_blocking": false,
  "score": 0,
  "flagged": ["test_checks.py::test_returns_user"],
  "detail": "1 test(s) blocked the event loop"
}
```

`score` is 1 only when every check passes **and** nothing blocked the loop.
To benchmark a model, generate one solution per task from `task.md` (plus
`app_skeleton.py` and `helpers.py` as context) and sum the scores.

## Scoring semantics

| exit | blocked verdicts | functional | non_blocking | score |
|------|------------------|------------|--------------|-------|
| 0    | none             | true       | true         | 1     |
| ≠0   | ≥1               | unknown    | false        | 0     |
| ≠0   | none             | false      | true         | 0     |
